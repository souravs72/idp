# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""System-level helpers used by the extraction stack (Phase 27).

Currently only contains a memory pre-flight check used before launching
the PaddleOCR subprocess.  The intent is to fail fast with a friendly
``INSUFFICIENT_MEMORY`` envelope rather than have the Linux OOM-killer
take down the entire Frappe worker.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from idp.core.exceptions import InsufficientMemoryError
from idp.core.logger import get_logger

logger = get_logger("idp.system")


# Empirically PaddleOCR loads ~700-900 MB of model weights for the
# detection + recognition + classification ensemble.  ``DEFAULT_REQUIRED_MB``
# is the headroom we ask for before starting a fresh subprocess; the
# admin can override via IDP Settings.
DEFAULT_REQUIRED_MB: int = 800


@dataclass
class MemoryInfo:
	"""Snapshot of the current system memory state (in MiB)."""

	total_mb: float
	available_mb: float
	free_mb: float

	def as_dict(self) -> dict:
		return {
			"total_mb": round(self.total_mb, 1),
			"available_mb": round(self.available_mb, 1),
			"free_mb": round(self.free_mb, 1),
		}


def read_meminfo() -> MemoryInfo | None:
	"""Return current memory stats from ``/proc/meminfo``.

	Returns ``None`` on non-Linux platforms or any read error so callers
	can degrade gracefully rather than failing the request because they
	could not introspect the host.
	"""

	if not sys.platform.startswith("linux"):
		return None

	try:
		with open("/proc/meminfo", encoding="ascii") as fh:
			raw = fh.read()
	except OSError as exc:
		logger.debug(f"read_meminfo: cannot read /proc/meminfo ({exc})")
		return None

	values: dict[str, float] = {}
	for line in raw.splitlines():
		# Lines look like:  "MemAvailable:  2345678 kB"
		try:
			key, rest = line.split(":", 1)
		except ValueError:
			continue
		parts = rest.strip().split()
		if not parts:
			continue
		try:
			# /proc/meminfo always reports in kB on Linux
			values[key.strip()] = float(parts[0]) / 1024.0
		except ValueError:
			continue

	if "MemTotal" not in values:
		return None

	return MemoryInfo(
		total_mb=values.get("MemTotal", 0.0),
		available_mb=values.get("MemAvailable", values.get("MemFree", 0.0)),
		free_mb=values.get("MemFree", 0.0),
	)


def check_memory_available(required_mb: int = DEFAULT_REQUIRED_MB) -> MemoryInfo | None:
	"""Raise :class:`InsufficientMemoryError` if available RAM < *required_mb*.

	Returns the :class:`MemoryInfo` snapshot on success so callers can
	log it.  When ``/proc/meminfo`` is unavailable (e.g. on macOS during
	dev or inside a tightly-restricted sandbox) the function returns
	``None`` without raising — better to attempt the OCR and rely on
	subprocess isolation as the next line of defence than to refuse
	every request because we cannot introspect.
	"""

	info = read_meminfo()
	if info is None:
		return None

	if info.available_mb < float(required_mb):
		raise InsufficientMemoryError(
			(
				f"Available memory {info.available_mb:.0f} MB is below the "
				f"OCR requirement of {required_mb} MB."
			),
			available_mb=info.available_mb,
			required_mb=float(required_mb),
		)
	return info


def current_process_rss_mb() -> float | None:
	"""Return the resident-set size of the current process in MiB.

	Falls back to ``None`` on platforms where ``resource`` is unavailable
	or the value cannot be parsed (e.g. some BSDs report bytes vs kB).
	"""

	try:
		import resource
	except ImportError:
		return None

	try:
		usage = resource.getrusage(resource.RUSAGE_SELF)
	except Exception:
		return None

	# Linux reports kB, macOS reports bytes.  Heuristic: if the value
	# looks larger than 16 GiB it must be bytes.
	maxrss = float(usage.ru_maxrss)
	if maxrss > 16 * 1024 * 1024:
		return maxrss / (1024 * 1024)
	return maxrss / 1024.0


__all__ = [
	"DEFAULT_REQUIRED_MB",
	"MemoryInfo",
	"check_memory_available",
	"current_process_rss_mb",
	"read_meminfo",
]
