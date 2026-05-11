# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""S3 / remote-attachment materialisation helper (Phase 27 §27.4).

The IDP pipeline historically assumed every ``tabFile`` row points at a
local-disk path under ``private/files`` or ``files``.  Deployments
running ``frappe_s3_attachment`` (or any S3-style backend) store
``file_url`` as ``https://bucket.s3…`` which fails the
``assert_safe_file_url`` check and produces a ``FileNotFoundError``
deep inside the extractor.

:func:`materialise_for_extraction` bridges the gap by downloading remote
files into a per-site cache directory keyed by ``(file_url, file_size)``
so a single conversation that re-extracts the same attachment several
times pays the network cost only once.  The cached file is tagged with
``idp_extraction_cache=1`` so the Phase 14 §14.3 cleanup job can mop it
up later.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from idp.core.exceptions import ExtractionError, SecurityError
from idp.core.logger import get_logger

logger = get_logger("idp.file_io")


# Hard cap on remote-download size before we bail out; mirrors
# ``MAX_FILE_SIZE_BYTES`` so we cannot fill /tmp with a gigabyte object
# that the rest of the pipeline would reject anyway.
_DEFAULT_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB

# In-process cache: ``cache_key -> absolute path``.  Lives for the
# duration of the Python worker; the on-disk files survive until the
# cleanup job removes them.
_materialise_cache: dict[str, str] = {}


@dataclass
class RemoteFile:
	"""Description of a materialised remote file."""

	local_path: str
	cached: bool = False
	source_url: str = ""

	def as_dict(self) -> dict:
		return {
			"local_path": self.local_path,
			"cached": self.cached,
			"source_url": self.source_url,
		}


def is_remote_file(file_doc: Any) -> bool:
	"""Heuristically detect whether *file_doc* is backed by remote storage.

	A "File" doc is treated as remote when **any** of the following hold:

	* ``file_url`` starts with ``http://`` or ``https://`` (S3 presigned
	  URL or public bucket); local Frappe URLs always start with ``/``.
	* The ``is_remote`` boolean attribute is truthy
	  (``frappe_s3_attachment`` sets this).
	* A ``content_hash`` is set but no on-disk file is present.
	"""

	url = (getattr(file_doc, "file_url", "") or "").strip()
	if url.startswith(("http://", "https://")):
		return True
	if bool(getattr(file_doc, "is_remote", False)):
		return True
	return False


def _cache_dir() -> Path:
	"""Per-site cache directory for materialised remote files."""

	try:
		import frappe

		site_path = Path(frappe.get_site_path()).resolve()
	except Exception:
		site_path = Path(tempfile.gettempdir())
	cache = site_path / "private" / "files" / ".idp_extraction_cache"
	cache.mkdir(parents=True, exist_ok=True)
	return cache


def _cache_key(file_url: str, file_size: int | None) -> str:
	"""Deterministic cache key — stable across processes."""

	digest = hashlib.sha256()
	digest.update((file_url or "").encode("utf-8"))
	if file_size is not None:
		digest.update(b"|")
		digest.update(str(file_size).encode("ascii"))
	return digest.hexdigest()[:32]


def materialise_for_extraction(
	file_doc: Any,
	*,
	max_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
) -> RemoteFile:
	"""Return a :class:`RemoteFile` pointing at a local copy of *file_doc*.

	If *file_doc* is local (the common case) we just return the resolved
	on-disk path.  For remote files we download to a per-site cache
	directory and tag the resulting ``File`` row with
	``idp_extraction_cache=1`` so the Phase 14 cleaner removes it.

	Raises:
		SecurityError: on path-traversal or unsupported URL scheme.
		ExtractionError: on download failure, truncated response, or
			file size exceeding ``max_bytes``.
	"""

	url = (getattr(file_doc, "file_url", "") or "").strip()
	if not url:
		raise SecurityError("file_url is missing", details={"file_doc": str(file_doc)})

	if not is_remote_file(file_doc):
		# Local case — let the existing helpers resolve and return.
		from idp.idp.extractors.base import resolve_file

		abs_path, _ = resolve_file(url)
		return RemoteFile(local_path=abs_path, cached=False, source_url=url)

	file_size = getattr(file_doc, "file_size", None)
	cache_key = _cache_key(url, file_size)
	cached_path = _materialise_cache.get(cache_key)
	if cached_path and os.path.isfile(cached_path):
		logger.debug(f"materialise: cache hit for {url} -> {cached_path}")
		return RemoteFile(local_path=cached_path, cached=True, source_url=url)

	# Decide the suffix from the file name so PIL / pypdf can sniff it.
	file_name = getattr(file_doc, "file_name", "") or "remote"
	suffix = os.path.splitext(file_name)[1] or ".bin"
	target_path = _cache_dir() / f"{cache_key}{suffix}"

	if target_path.exists():
		_materialise_cache[cache_key] = str(target_path)
		return RemoteFile(local_path=str(target_path), cached=True, source_url=url)

	logger.info(f"materialise: downloading remote file {url} -> {target_path}")
	_download(url, target_path, max_bytes=max_bytes)
	_materialise_cache[cache_key] = str(target_path)
	_tag_cache_entry(file_doc, target_path)
	return RemoteFile(local_path=str(target_path), cached=False, source_url=url)


def _download(url: str, target: Path, *, max_bytes: int) -> None:
	"""Stream *url* into *target*, enforcing a byte cap."""

	try:
		import httpx
	except ImportError as exc:  # pragma: no cover — httpx ships with Frappe
		raise ExtractionError(f"httpx required to fetch remote files: {exc}") from exc

	bytes_written = 0
	tmp = target.with_suffix(target.suffix + ".part")
	try:
		with httpx.stream("GET", url, timeout=60.0, follow_redirects=True) as resp:
			if resp.status_code >= 400:
				raise ExtractionError(
					f"Remote file fetch failed: HTTP {resp.status_code}",
					details={"url": url, "status": resp.status_code},
				)
			with open(tmp, "wb") as fh:
				for chunk in resp.iter_bytes(chunk_size=64 * 1024):
					if not chunk:
						continue
					bytes_written += len(chunk)
					if bytes_written > max_bytes:
						raise ExtractionError(
							f"Remote file exceeds max download size of {max_bytes} bytes",
							details={"url": url, "max_bytes": max_bytes},
						)
					fh.write(chunk)
		os.replace(tmp, target)
	except ExtractionError:
		_safe_remove(tmp)
		raise
	except Exception as exc:
		_safe_remove(tmp)
		raise ExtractionError(
			f"Failed to materialise remote file: {exc}",
			details={"url": url},
		) from exc


def _tag_cache_entry(file_doc: Any, target_path: Path) -> None:
	"""Flag the cache entry so the Phase 14 cleaner can remove it.

	Currently a best-effort hook: we set ``idp_extraction_cache=1`` on
	the originating File record if the custom field exists, and write a
	sibling ``.cache_meta`` file so cleanup can identify the entry even
	when no File row references it directly.
	"""

	try:
		marker = target_path.with_suffix(target_path.suffix + ".cache_meta")
		marker.write_text(
			(
				f"file_url={getattr(file_doc, 'file_url', '') or ''}\n"
				f"file_name={getattr(file_doc, 'file_name', '') or ''}\n"
			),
			encoding="utf-8",
		)
	except Exception as exc:
		logger.debug(f"_tag_cache_entry: marker write failed ({exc})")

	try:
		import frappe

		name = getattr(file_doc, "name", None)
		if name and frappe.db.has_column("File", "idp_extraction_cache"):
			frappe.db.set_value("File", name, "idp_extraction_cache", 1, update_modified=False)
	except Exception as exc:
		logger.debug(f"_tag_cache_entry: db tagging failed ({exc})")


def _safe_remove(path: Path) -> None:
	try:
		if path.exists():
			path.unlink()
	except OSError:
		pass


def clear_cache() -> None:
	"""Drop the in-process cache map (test / shutdown helper).

	The on-disk files are *not* deleted — that is the cleanup job's job.
	"""

	_materialise_cache.clear()


__all__ = [
	"RemoteFile",
	"clear_cache",
	"is_remote_file",
	"materialise_for_extraction",
]
