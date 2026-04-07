# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Document extraction API endpoint.

Orchestrates the full IDP extraction pipeline:
file resolution -> content extraction -> OCR (if needed) ->
field mapping -> validation -> return for user review.
"""

import time

import frappe

from idp.core.config import get_default_company
from idp.core.constants import SUPPORTED_DOCTYPES
from idp.core.exceptions import IDPError
from idp.core.logger import get_logger
from idp.idp.extractors import extract_content
from idp.idp.mappers import FieldMapper, MappedDocument
from idp.idp.validators import validate_business_rules, validate_schema

logger = get_logger("idp.api.extract")


@frappe.whitelist()
def extract_document(
	file_url: str,
	target_doctype: str,
	company: str | None = None,
	language: str = "en",
) -> dict:
	"""Extract structured data from an uploaded document.

	Runs the full IDP pipeline:

	1. Resolve and extract file content (Phase 3).
	2. OCR if image or scanned PDF (Phase 2 — transparent).
	3. Map extracted content to *target_doctype* schema (Phase 4).
	4. Validate mapped data (Phase 5).
	5. Return mapped data for user review before creation.

	Args:
		file_url: Frappe file URL (e.g. ``/private/files/invoice.pdf``).
		target_doctype: ERPNext DocType to map to (e.g. ``Purchase Invoice``).
		company: Company context. Falls back to ``get_default_company()``.
		language: OCR language code (default ``en``).

	Returns:
		dict with keys:
			- ``success``: bool
			- ``extracted_data``: ``{header: {...}, items: [...]}``
			- ``unmapped_fields``: list of fields that could not be mapped
			- ``validation``: ``{is_valid, errors, warnings}``
			- ``confidence``: float (average extraction confidence)
			- ``processing_time_ms``: int
	"""
	start = time.monotonic()
	company = company or get_default_company()

	# --- Input validation ---
	if not file_url:
		frappe.throw("file_url is required.", frappe.ValidationError)

	if target_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			f'Unsupported target DocType: "{target_doctype}". Supported: {", ".join(SUPPORTED_DOCTYPES)}',
			frappe.ValidationError,
		)

	try:
		# 1. Extract content from file
		extraction = extract_content(file_url, lang=language)

		# 2. Map to target DocType schema
		mapper = FieldMapper()
		mapped: MappedDocument = mapper.map_fields(extraction, target_doctype, company=company)

		# 3. Validate
		schema_result = validate_schema(mapped, company)
		biz_warnings = validate_business_rules(mapped, company)

		# Build validation summary
		validation = {
			"is_valid": schema_result.is_valid,
			"errors": [
				{"field": e.field, "message": e.message, "severity": e.severity} for e in schema_result.errors
			],
			"warnings": (
				[
					{"field": w.field, "message": w.message, "severity": w.severity}
					for w in schema_result.warnings
				]
				+ [{"field": "", "message": w, "severity": "warning"} for w in biz_warnings]
			),
			"resolved_links": schema_result.resolved_links,
			"missing_masters": schema_result.missing_masters,
		}

		elapsed_ms = int((time.monotonic() - start) * 1000)

		logger.info(
			f"Extraction complete | doctype={target_doctype} file={file_url} "
			f"valid={schema_result.is_valid} time={elapsed_ms}ms"
		)

		return {
			"success": True,
			"extracted_data": {
				"doctype": mapped.doctype,
				"header": mapped.header,
				"items": mapped.items,
			},
			"unmapped_fields": mapped.unmapped_fields,
			"confidence_scores": mapped.confidence_scores,
			"validation": validation,
			"confidence": extraction.confidence,
			"processing_time_ms": elapsed_ms,
		}

	except IDPError as exc:
		elapsed_ms = int((time.monotonic() - start) * 1000)
		logger.warning(f"Extraction failed | file={file_url} error={exc}")
		return {
			"success": False,
			"error": str(exc),
			"error_type": type(exc).__name__,
			"details": exc.details,
			"processing_time_ms": elapsed_ms,
		}

	except Exception as exc:
		elapsed_ms = int((time.monotonic() - start) * 1000)
		logger.error(f"Unexpected extraction error | file={file_url} error={exc}")
		frappe.throw(
			f"Extraction failed: {exc}",
			title="IDP Extraction Error",
		)
