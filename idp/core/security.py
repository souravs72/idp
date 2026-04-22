# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Security guards for the IDP pipeline (Phase 14).

This module centralises three defensive checks used by the upload,
extract, and create APIs:

1. **File-type verification (magic bytes).**  MIME types supplied by
   the client or inferred from the filename cannot be trusted, so we
   sniff the first few bytes of the file and compare against the
   signatures of the formats the IDP pipeline understands.

2. **Path traversal prevention.**  All file paths are normalised and
   required to resolve inside the site's ``private/files`` or
   ``public/files`` directories.  Any attempt to escape (e.g.
   ``../../etc/passwd``) raises :class:`SecurityError`.

3. **Permission gating.**  Before creating / comparing against an
   ERPNext record, we confirm the caller has ``read`` permission on
   the target DocType.  This prevents a low-privilege user from
   probing records they cannot open in the desk.

Every function raises :class:`idp.core.exceptions.SecurityError` on
failure so callers can uniformly surface 403-style responses.
"""

from __future__ import annotations

import os
from pathlib import Path

import frappe

from idp.core.exceptions import SecurityError
from idp.core.logger import get_logger

logger = get_logger("idp.security")


# ---------------------------------------------------------------------------
# Magic-byte signatures
# ---------------------------------------------------------------------------
#
# Each entry maps a MIME type to a tuple of ``(offset, signature_bytes)``.
# Multiple signatures per MIME are supported (some formats start with
# any of several magic numbers — e.g. JPEG has several SOI variants).

_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
	"application/pdf": [(0, b"%PDF-")],
	"image/png": [(0, b"\x89PNG\r\n\x1a\n")],
	"image/jpeg": [
		(0, b"\xff\xd8\xff\xe0"),
		(0, b"\xff\xd8\xff\xe1"),
		(0, b"\xff\xd8\xff\xe2"),
		(0, b"\xff\xd8\xff\xdb"),
		(0, b"\xff\xd8\xff\xee"),
	],
	"image/gif": [(0, b"GIF87a"), (0, b"GIF89a")],
	"image/tiff": [(0, b"II*\x00"), (0, b"MM\x00*")],
	"image/bmp": [(0, b"BM")],
	"image/webp": [(0, b"RIFF")],  # followed by WEBP at offset 8
}


# MIME types the IDP pipeline currently supports end-to-end.  Extensions
# beyond this set (e.g. DOCX) are rejected at ingestion.
SUPPORTED_MIME_TYPES: set[str] = {
	"application/pdf",
	"image/png",
	"image/jpeg",
	"image/tiff",
	"image/bmp",
	"image/webp",
}


def detect_mime_by_magic(data: bytes) -> str | None:
	"""Return the best-guess MIME type for *data* based on magic bytes.

	Only recognises the formats listed in :data:`_SIGNATURES`.  Returns
	``None`` if no signature matches — caller decides how strict to be.
	"""
	if not data:
		return None

	for mime, signatures in _SIGNATURES.items():
		for offset, sig in signatures:
			if len(data) >= offset + len(sig) and data[offset:offset + len(sig)] == sig:
				return mime
	return None


def verify_file_type(
	path_or_data: str | bytes,
	expected_mime: str | None = None,
	max_bytes: int = 64,
) -> str:
	"""Sniff *path_or_data* and raise if it isn't a supported format.

	Args:
		path_or_data: Either an absolute filesystem path (str) or a
			bytes blob (useful for tests).
		expected_mime: If provided, raise unless the sniffed MIME
			matches exactly.  A guard against the classic "user
			uploaded a .pdf but it's actually an .exe" attack.
		max_bytes: How many leading bytes to read when the argument is
			a path.

	Returns:
		The sniffed MIME type.
	"""
	if isinstance(path_or_data, (bytes, bytearray)):
		head = bytes(path_or_data[:max_bytes])
	else:
		try:
			with open(path_or_data, "rb") as fh:
				head = fh.read(max_bytes)
		except OSError as exc:
			raise SecurityError(f"Cannot read file for type check: {exc}") from exc

	mime = detect_mime_by_magic(head)
	if mime is None:
		raise SecurityError(
			"Unrecognised file signature.",
			details={"first_bytes": head[:8].hex()},
		)

	if mime not in SUPPORTED_MIME_TYPES:
		raise SecurityError(
			f"Unsupported file type: {mime}",
			details={"mime": mime, "supported": sorted(SUPPORTED_MIME_TYPES)},
		)

	if expected_mime and mime != expected_mime:
		raise SecurityError(
			f"File type mismatch: claimed {expected_mime!r}, actually {mime!r}",
			details={"claimed": expected_mime, "actual": mime},
		)

	return mime


# ---------------------------------------------------------------------------
# Path traversal
# ---------------------------------------------------------------------------


def _site_file_roots() -> list[Path]:
	"""Return the set of directories that files may legitimately live in."""
	try:
		site_path = Path(frappe.get_site_path()).resolve()
	except Exception:
		# In pure-mode tests there is no site — fall back to cwd.
		site_path = Path.cwd().resolve()
	return [site_path / "private" / "files", site_path / "public" / "files"]


def assert_safe_file_url(file_url: str) -> str:
	"""Validate a Frappe File URL and return its on-disk path.

	Accepts URLs shaped like ``/private/files/...`` or
	``/files/...`` (public) and rejects anything else.  The returned
	path is guaranteed to live inside one of the site's file roots,
	so callers can safely open it.
	"""
	if not file_url or not isinstance(file_url, str):
		raise SecurityError("file_url must be a non-empty string.")

	url = file_url.strip()
	if url.startswith("/private/files/"):
		relative = url[len("/private/files/"):]
		base = _site_file_roots()[0]
	elif url.startswith("/files/"):
		relative = url[len("/files/"):]
		base = _site_file_roots()[1]
	else:
		raise SecurityError(
			"file_url must start with /private/files/ or /files/.",
			details={"file_url": file_url},
		)

	if not relative or relative.startswith("/"):
		raise SecurityError("file_url has an empty or absolute remainder.", details={"file_url": file_url})

	candidate = (base / relative).resolve()
	base_resolved = base.resolve()
	try:
		candidate.relative_to(base_resolved)
	except ValueError as exc:
		raise SecurityError(
			"Path traversal detected.",
			details={"file_url": file_url, "resolved": str(candidate)},
		) from exc

	return str(candidate)


def is_safe_file_url(file_url: str) -> bool:
	"""Boolean counterpart to :func:`assert_safe_file_url`."""
	try:
		assert_safe_file_url(file_url)
	except SecurityError:
		return False
	return True


# ---------------------------------------------------------------------------
# Permission gating
# ---------------------------------------------------------------------------


def assert_user_can_read(doctype: str, user: str | None = None) -> None:
	"""Raise :class:`SecurityError` if *user* lacks ``read`` on *doctype*.

	Uses ``frappe.has_permission`` under the hood so role permission
	managers, user permissions, and the ignore_permissions flag
	(for background jobs) are all honoured.
	"""
	try:
		allowed = frappe.has_permission(doctype=doctype, ptype="read", user=user, throw=False)
	except Exception as exc:  # pragma: no cover — defensive
		raise SecurityError(f"Permission check failed for {doctype}: {exc}") from exc

	if not allowed:
		raise SecurityError(
			f"User lacks read permission on {doctype}.",
			details={"doctype": doctype, "user": user or getattr(frappe.session, "user", "?")},
		)


def sanitize_string(value: str, max_length: int = 512) -> str:
	"""Strip control characters and trim to *max_length*.

	Intended for free-form text that will be fed into SQL or a log
	line.  Not a replacement for parameterised queries — just defence
	in depth against the worst accidents.
	"""
	if value is None:
		return ""
	cleaned = "".join(ch for ch in str(value) if ch.isprintable() or ch in ("\t", "\n"))
	return cleaned[:max_length]
