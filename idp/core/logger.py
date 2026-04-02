"""Structured logging for the IDP module.

Wraps :func:`frappe.logger` to provide named loggers under the ``idp``
namespace and convenience functions for logging extraction / OCR events
with structured metadata.
"""

import logging

import frappe


def get_logger(module: str = "idp") -> logging.Logger:
	"""Return a named logger under the ``idp`` namespace.

	Args:
		module: Sub-module name, e.g. ``"idp.ocr"`` or ``"idp.extractors"``.
			Defaults to the root ``"idp"`` logger.

	Returns:
		A :class:`logging.Logger` wired to Frappe's log infrastructure.
	"""
	return frappe.logger(module, allow_site=True)


def log_extraction(
	file_url: str,
	doctype: str,
	status: str,
	duration_ms: int,
	**kwargs,
) -> None:
	"""Log an extraction attempt with structured metadata.

	Args:
		file_url: URL/path of the source document.
		doctype: Target ERPNext DocType (e.g. ``"Purchase Invoice"``).
		status: Outcome — ``"success"``, ``"failed"``, ``"partial"``.
		duration_ms: Processing time in milliseconds.
		**kwargs: Additional metadata (``confidence``, ``pages``, ``error``, etc.).
	"""
	logger = get_logger("idp.extraction")
	extra = {
		"file_url": file_url,
		"doctype": doctype,
		"status": status,
		"duration_ms": duration_ms,
		**kwargs,
	}
	msg = f"Extraction {status} | doctype={doctype} | file={file_url} | {duration_ms}ms"

	if status == "failed":
		logger.error(msg, extra=extra)
	elif status == "partial":
		logger.warning(msg, extra=extra)
	else:
		logger.info(msg, extra=extra)


def log_ocr_result(
	file_url: str,
	pages: int,
	avg_confidence: float,
	language: str,
) -> None:
	"""Log OCR processing results.

	Args:
		file_url: URL/path of the processed document.
		pages: Number of pages processed.
		avg_confidence: Average OCR confidence across all pages (0.0-1.0).
		language: OCR language code used.
	"""
	logger = get_logger("idp.ocr")
	msg = (
		f"OCR complete | file={file_url} | pages={pages} "
		f"| confidence={avg_confidence:.2f} | lang={language}"
	)
	extra = {
		"file_url": file_url,
		"pages": pages,
		"avg_confidence": avg_confidence,
		"language": language,
	}

	if avg_confidence < 0.50:
		logger.warning(msg, extra=extra)
	else:
		logger.info(msg, extra=extra)
