# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unified project logger for the IDP module.

Delegates to Frappe's ``frappe.logger("idp")`` so records land in the
standard bench logs folder (``logs/idp.log``) with rotation, *and* in
the per-site logs folder (``sites/<site>/logs/idp.log``) when a site
context is available.  Falls back to a plain stderr handler when
Frappe is not importable (pure unit tests).

Every record has the shape:

	YYYY-MM-DD HH:MM:SS LEVEL idp tool=<name> <msg> [k=v ...]
"""

import logging

_LOGGER_NAME = "idp"
_FALLBACK_FORMAT = "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s"
_FALLBACK_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _frappe_logger() -> logging.Logger | None:
	"""Return ``frappe.logger("idp")`` if Frappe is available, else None."""

	try:
		import frappe
		from frappe.utils.logger import get_logger as _frappe_get_logger
	except Exception:
		return None
	try:
		logger = _frappe_get_logger(
			_LOGGER_NAME,
			allow_site=True,
			max_size=1_000_000,
			file_count=10,
		)
	except Exception:
		return None
	# Frappe's default level is WARNING in production; lift to INFO so
	# our tool-level events surface in ``logs/idp.log`` without admins
	# having to flip ``developer_mode``.
	if logger.level > logging.INFO or logger.level == logging.NOTSET:
		logger.setLevel(logging.INFO)
	return logger


def _fallback_logger() -> logging.Logger:
	"""Plain stderr logger for pure-Python contexts (tests, scripts)."""

	logger = logging.getLogger(_LOGGER_NAME)
	if not logger.handlers:
		handler = logging.StreamHandler()
		handler.setFormatter(logging.Formatter(_FALLBACK_FORMAT, datefmt=_FALLBACK_DATEFMT))
		logger.addHandler(handler)
		logger.setLevel(logging.INFO)
		logger.propagate = False
	return logger


def get_logger(*_args, **_kwargs) -> logging.Logger:
	"""Return the unified project logger.

	Positional / keyword arguments are accepted but ignored so legacy
	call sites such as ``get_logger("idp.ocr")`` continue to work
	without immediate refactor.  The returned logger always writes to
	the standard Frappe bench + site logs when Frappe is available.
	"""

	return _frappe_logger() or _fallback_logger()


def log_event(tool: str, message: str, level: str = "info", **extra) -> None:
	"""Emit a structured log line with ``tool=<name>`` prefix.

	Args:
		tool: Short identifier for the call site, e.g. ``"ocr"``, ``"extraction"``,
			``"agent"``, ``"reconciliation"``.
		message: Human-readable message.
		level: Logging level name (``info`` | ``warning`` | ``error`` | ``debug``).
		**extra: Optional ``key=value`` fields appended to the message.
	"""

	logger = get_logger()
	suffix = " ".join(f"{k}={v}" for k, v in extra.items())
	payload = f"tool={tool} {message}".strip()
	if suffix:
		payload = f"{payload} {suffix}"
	getattr(logger, level, logger.info)(payload)


def log_extraction(
	file_url: str,
	doctype: str,
	status: str,
	duration_ms: int,
	**kwargs,
) -> None:
	"""Log an extraction attempt as a structured event."""

	level = "error" if status == "failed" else ("warning" if status == "partial" else "info")
	log_event(
		"extraction",
		f"{status} doctype={doctype} file={file_url} {duration_ms}ms",
		level=level,
		**kwargs,
	)


def log_ocr_result(
	file_url: str,
	pages: int,
	avg_confidence: float,
	language: str,
) -> None:
	"""Log OCR processing results as a structured event."""

	level = "warning" if avg_confidence < 0.50 else "info"
	log_event(
		"ocr",
		f"complete file={file_url} pages={pages} confidence={avg_confidence:.2f} lang={language}",
		level=level,
	)
