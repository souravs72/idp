# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Audit logging helper — persists pipeline events to *IDP Document Log*.

Every meaningful operation of the IDP pipeline (extraction, record
creation, comparison, bank-statement processing) funnels through this
module so there is a single, consistent persistence layer for both
observability queries and compliance audits.

Design notes
------------
- **Never raises.**  Audit failures must not break the host request.
  Every public entry-point swallows exceptions and logs them under the
  ``idp.audit`` logger.
- **Read-only feature flag.**  If ``enable_audit_log`` is disabled in
  IDP Settings (when the field exists), the helpers become no-ops.
  Audit is on by default when the flag is absent.
- **Structured payloads.**  JSON fields (``extraction_data``,
  ``validation_errors``) are stored as ``json.dumps(...)`` strings so
  Frappe's JSON field treats them as opaque blobs without re-encoding.
- **Status vocabulary.**  Matches the DocType Select exactly:
  ``Uploaded | Extracting | Extracted | Creating | Created | Failed``.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.audit")


# Status values accepted by the IDP Document Log DocType.
VALID_STATUSES = {
	"Uploaded", "Extracting", "Extracted", "Creating", "Created", "Failed",
}


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def is_audit_enabled() -> bool:
	"""Return True unless IDP Settings explicitly disables audit logging.

	The settings field ``enable_audit_log`` is optional — if missing,
	audit defaults to ON so that Phase 13 upgrades are captured
	without requiring a migration.
	"""
	try:
		single = frappe.get_cached_doc("IDP Settings")
	except Exception:  # DocType missing / install in progress
		return True
	flag = getattr(single, "enable_audit_log", None)
	# None means field absent -> default enabled.
	return True if flag is None else bool(flag)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _jsonify(value: Any) -> str | None:
	"""Serialise *value* into a JSON string suitable for a JSON field."""
	if value is None:
		return None
	try:
		return json.dumps(value, default=str, ensure_ascii=False)
	except (TypeError, ValueError):
		return json.dumps(str(value))


def _truncate(text: str | None, limit: int = 2000) -> str | None:
	if text is None:
		return None
	text = str(text)
	return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_event(
	*,
	file_url: str | None = None,
	file_name: str | None = None,
	mime_type: str | None = None,
	target_doctype: str | None = None,
	company: str | None = None,
	status: str = "Uploaded",
	processing_time_ms: int | None = None,
	ocr_confidence: float | None = None,
	ocr_language: str | None = None,
	created_doctype: str | None = None,
	created_document: str | None = None,
	extraction_data: Any = None,
	validation_errors: Any = None,
	error_message: str | None = None,
	user: str | None = None,
) -> str | None:
	"""Persist a single *IDP Document Log* row.

	Returns the new log's name on success, ``None`` on failure.  All
	arguments are optional because different pipeline stages have
	different context; the DocType only enforces ``file_url`` as
	required.
	"""
	if not is_audit_enabled():
		return None

	if not file_url:
		# Required by the DocType — fall back to a placeholder rather
		# than raising, so callers never have to branch on audit.
		file_url = "<unknown>"

	if status not in VALID_STATUSES:
		logger.warning("Rejecting invalid audit status: %s", status)
		status = "Failed" if error_message else "Uploaded"

	try:
		doc = frappe.get_doc({
			"doctype": "IDP Document Log",
			"file_url": file_url,
			"file_name": file_name,
			"mime_type": mime_type,
			"target_doctype": target_doctype,
			"company": company,
			"user": user or frappe.session.user,
			"status": status,
			"processing_time_ms": processing_time_ms,
			"ocr_confidence": ocr_confidence,
			"ocr_language": ocr_language,
			"created_doctype": created_doctype,
			"created_document": created_document,
			"extraction_data": _jsonify(extraction_data),
			"validation_errors": _jsonify(validation_errors),
			"error_message": _truncate(error_message),
		})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()  # ensure the log survives even on later failure
		return doc.name
	except Exception as exc:  # pragma: no cover — defensive
		logger.error("Audit insert failed: %s", exc, exc_info=True)
		return None


def log_extraction_event(
	*,
	file_url: str,
	target_doctype: str,
	success: bool,
	processing_time_ms: int,
	confidence: float | None = None,
	language: str | None = None,
	extraction_data: Any = None,
	validation_errors: Any = None,
	error_message: str | None = None,
	company: str | None = None,
	mime_type: str | None = None,
	file_name: str | None = None,
) -> str | None:
	"""Convenience wrapper for the extract-only pipeline."""
	return log_event(
		file_url=file_url,
		file_name=file_name,
		mime_type=mime_type,
		target_doctype=target_doctype,
		company=company,
		status="Extracted" if success else "Failed",
		processing_time_ms=processing_time_ms,
		ocr_confidence=confidence,
		ocr_language=language,
		extraction_data=extraction_data,
		validation_errors=validation_errors,
		error_message=error_message,
	)


def log_creation_event(
	*,
	target_doctype: str,
	success: bool,
	created_name: str | None = None,
	file_url: str | None = None,
	company: str | None = None,
	warnings: Any = None,
	error_message: str | None = None,
) -> str | None:
	"""Convenience wrapper for record creation."""
	return log_event(
		file_url=file_url or "<create>",
		target_doctype=target_doctype,
		company=company,
		status="Created" if success else "Failed",
		created_doctype=target_doctype if success else None,
		created_document=created_name if success else None,
		validation_errors=warnings,
		error_message=error_message,
	)


def log_comparison_event(
	*,
	file_url: str,
	compare_doctype: str,
	compare_docname: str,
	success: bool,
	processing_time_ms: int,
	summary: str | None = None,
	error_message: str | None = None,
	company: str | None = None,
) -> str | None:
	"""Convenience wrapper for comparison runs.

	We reuse the ``Extracted`` status since a comparison implies a full
	extraction was performed; the payload captures the comparison summary.
	"""
	return log_event(
		file_url=file_url,
		target_doctype=compare_doctype,
		company=company,
		status="Extracted" if success else "Failed",
		processing_time_ms=processing_time_ms,
		created_doctype=compare_doctype,
		created_document=compare_docname,
		extraction_data={"comparison_summary": summary} if summary else None,
		error_message=error_message,
	)


def log_bank_event(
	*,
	file_url: str,
	success: bool,
	processing_time_ms: int,
	transaction_count: int = 0,
	bank_account: str | None = None,
	matched: int = 0,
	unmatched: int = 0,
	error_message: str | None = None,
	company: str | None = None,
) -> str | None:
	"""Convenience wrapper for bank-statement extraction / reconciliation."""
	return log_event(
		file_url=file_url,
		target_doctype="Bank Transaction",
		company=company,
		status="Extracted" if success else "Failed",
		processing_time_ms=processing_time_ms,
		extraction_data={
			"bank_account": bank_account,
			"transaction_count": transaction_count,
			"matched": matched,
			"unmatched": unmatched,
		} if success else None,
		error_message=error_message,
	)


# ---------------------------------------------------------------------------
# Read-side helpers (used by observability endpoints and tests)
# ---------------------------------------------------------------------------


def get_recent_logs(limit: int = 50, filters: dict | None = None) -> list[dict]:
	"""Return the most recent *IDP Document Log* rows.

	Args:
		limit: Max rows to return.
		filters: Additional Frappe-style filters (e.g. ``{"status": "Failed"}``).

	Returns:
		List of dicts with log fields.
	"""
	return frappe.get_all(
		"IDP Document Log",
		filters=filters or {},
		fields=[
			"name", "file_url", "file_name", "target_doctype", "company",
			"user", "status", "processing_time_ms", "ocr_confidence",
			"created_doctype", "created_document", "creation",
		],
		order_by="creation desc",
		limit=limit,
	)
