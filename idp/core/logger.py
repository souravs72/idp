# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unified project logger for the IDP module.

All IDP code logs through a single ``idp`` logger with a fixed format:

	YYYY-MM-DD HH:MM:SS | <processName> | idp | <LEVEL> | tool=<name> <msg>

Sub-module loggers were removed — callers identify themselves through
the ``tool=`` field on the log line instead of via the logger name.
"""

import logging
import multiprocessing

_LOGGER_NAME = "idp"
_FORMAT = "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _ensure_handler(logger: logging.Logger) -> None:
	"""Attach a stream handler with the unified format if missing."""

	if logger.handlers:
		return
	handler = logging.StreamHandler()
	handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
	logger.addHandler(handler)
	logger.setLevel(logging.INFO)
	# Allow the root logger to also process the record (Frappe sometimes
	# attaches its own handler to root); avoid double-printing by setting
	# propagate=False since our stream handler already prints to stderr.
	logger.propagate = False


def get_logger(*_args, **_kwargs) -> logging.Logger:
	"""Return the unified project logger.

	Positional / keyword arguments are accepted but ignored so legacy call
	sites such as ``get_logger("idp.ocr")`` continue to work without
	immediate refactor.  The returned logger is always the single ``idp``
	logger configured with the unified format.
	"""

	logger = logging.getLogger(_LOGGER_NAME)
	_ensure_handler(logger)
	# Preserve the multiprocessing process name in the format (helps when
	# OCR runs in a subprocess).
	multiprocessing.current_process()  # touch to ensure name is populated
	return logger


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
