# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Document comparison API endpoints.

Provides endpoints to compare extracted document data against existing
ERPNext records, and to auto-find matching records.
"""

import time

import frappe

from idp.core.audit import log_comparison_event
from idp.core.config import get_default_company
from idp.core.constants import SUPPORTED_DOCTYPES
from idp.core.exceptions import IDPError
from idp.core.logger import get_logger
from idp.comparison.engine import compare_with_record
from idp.comparison.engine import find_matching_record as _find_match
from idp.extractors import extract_content
from idp.mappers import FieldMapper, MappedDocument

logger = get_logger("idp.api.compare")


@frappe.whitelist()
def compare_document(
	file_url: str,
	compare_doctype: str,
	compare_docname: str,
	company: str | None = None,
	language: str = "en",
) -> dict:
	"""Extract data from a document and compare with an existing record.

	Runs the extraction pipeline and then compares the result field-by-field
	against the specified ERPNext record.

	Args:
		file_url: Frappe file URL (e.g. ``/private/files/invoice.pdf``).
		compare_doctype: DocType of the record to compare against
			(e.g. ``Purchase Order``).
		compare_docname: Name of the specific record (e.g. ``PO-00042``).
		company: Company context. Falls back to ``get_default_company()``.
		language: OCR language code (default ``en``).

	Returns:
		dict with keys:
			- ``success``: bool
			- ``comparison``: serialised ``ComparisonResult``
			- ``extracted_data``: ``{header, items}``
			- ``processing_time_ms``: int
	"""
	start = time.monotonic()
	company = company or get_default_company()

	# --- Input validation ---
	if not file_url:
		frappe.throw("file_url is required.", frappe.ValidationError)

	if not compare_docname:
		frappe.throw("compare_docname is required.", frappe.ValidationError)

	if compare_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			f'Unsupported DocType: "{compare_doctype}".',
			frappe.ValidationError,
		)

	try:
		# 1. Extract content and map
		extraction = extract_content(file_url, lang=language)
		mapper = FieldMapper()
		mapped: MappedDocument = mapper.map_fields(extraction, compare_doctype, company=company)

		# 2. Compare with existing record
		result = compare_with_record(mapped, compare_doctype, compare_docname)

		elapsed_ms = int((time.monotonic() - start) * 1000)

		logger.info(
			f"Comparison complete | {compare_doctype}/{compare_docname} "
			f"matches={len(result.matches)} discrepancies={len(result.discrepancies)} "
			f"time={elapsed_ms}ms"
		)

		log_comparison_event(
			file_url=file_url,
			compare_doctype=compare_doctype,
			compare_docname=compare_docname,
			success=True,
			processing_time_ms=elapsed_ms,
			summary=result.summary,
			company=company,
		)

		return {
			"success": True,
			"comparison": _serialize_comparison(result),
			"extracted_data": {
				"doctype": mapped.doctype,
				"header": mapped.header,
				"items": mapped.items,
			},
			"processing_time_ms": elapsed_ms,
		}

	except IDPError as exc:
		elapsed_ms = int((time.monotonic() - start) * 1000)
		logger.warning(f"Comparison failed | {compare_doctype}/{compare_docname} error={exc}")
		log_comparison_event(
			file_url=file_url,
			compare_doctype=compare_doctype,
			compare_docname=compare_docname,
			success=False,
			processing_time_ms=elapsed_ms,
			error_message=f"{type(exc).__name__}: {exc}",
			company=company,
		)
		return {
			"success": False,
			"error": str(exc),
			"error_type": type(exc).__name__,
			"details": exc.details,
			"processing_time_ms": elapsed_ms,
		}

	except Exception as exc:
		elapsed_ms = int((time.monotonic() - start) * 1000)
		logger.error(f"Unexpected comparison error: {exc}")
		log_comparison_event(
			file_url=file_url,
			compare_doctype=compare_doctype,
			compare_docname=compare_docname,
			success=False,
			processing_time_ms=elapsed_ms,
			error_message=f"Unexpected: {exc}",
			company=company,
		)
		frappe.throw(
			f"Comparison failed: {exc}",
			title="IDP Comparison Error",
		)


@frappe.whitelist()
def find_matching_record(
	file_url: str,
	target_doctype: str = "Purchase Order",
	company: str | None = None,
	language: str = "en",
) -> dict:
	"""Extract data and auto-find a matching ERPNext record.

	Uses the Phase 7 matching strategies (reference number, supplier + date +
	total, supplier + item overlap) to find the best matching record.

	Args:
		file_url: Frappe file URL.
		target_doctype: DocType to search within (default ``Purchase Order``).
		company: Company context.
		language: OCR language code.

	Returns:
		dict with keys:
			- ``found``: bool
			- ``doctype``: str
			- ``docname``: str or None
			- ``extracted_data``: ``{header, items}``
	"""
	company = company or get_default_company()

	if not file_url:
		frappe.throw("file_url is required.", frappe.ValidationError)

	if target_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			f'Unsupported DocType: "{target_doctype}".',
			frappe.ValidationError,
		)

	try:
		# 1. Extract and map
		extraction = extract_content(file_url, lang=language)
		mapper = FieldMapper()
		mapped: MappedDocument = mapper.map_fields(extraction, target_doctype, company=company)

		# 2. Find matching record
		match_name = _find_match(mapped, target_doctype, company=company)

		if match_name:
			logger.info(f"Found matching {target_doctype}: {match_name}")
		else:
			logger.info(f"No matching {target_doctype} found for {file_url}")

		return {
			"found": match_name is not None,
			"doctype": target_doctype,
			"docname": match_name,
			"extracted_data": {
				"doctype": mapped.doctype,
				"header": mapped.header,
				"items": mapped.items,
			},
		}

	except IDPError as exc:
		logger.warning(f"Match search failed | file={file_url} error={exc}")
		return {
			"found": False,
			"doctype": target_doctype,
			"docname": None,
			"error": str(exc),
			"error_type": type(exc).__name__,
		}

	except Exception as exc:
		logger.error(f"Unexpected match search error: {exc}")
		frappe.throw(
			f"Match search failed: {exc}",
			title="IDP Match Error",
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_comparison(result) -> dict:
	"""Convert a ComparisonResult dataclass to a JSON-safe dict."""
	return {
		"doctype": result.doctype,
		"docname": result.docname,
		"matches": [
			{
				"field": fc.field,
				"label": fc.label,
				"document_value": fc.document_value,
				"record_value": fc.record_value,
				"status": fc.status,
				"difference": fc.difference,
			}
			for fc in result.matches
		],
		"discrepancies": [
			{
				"field": fc.field,
				"label": fc.label,
				"document_value": fc.document_value,
				"record_value": fc.record_value,
				"status": fc.status,
				"difference": fc.difference,
			}
			for fc in result.discrepancies
		],
		"missing_in_document": result.missing_in_document,
		"missing_in_record": result.missing_in_record,
		"items_comparison": [
			{
				"item_code": ic.item_code,
				"item_name": ic.item_name,
				"status": ic.status,
				"field_comparisons": [
					{
						"field": fc.field,
						"label": fc.label,
						"document_value": fc.document_value,
						"record_value": fc.record_value,
						"status": fc.status,
						"difference": fc.difference,
					}
					for fc in ic.field_comparisons
				],
			}
			for ic in result.items_comparison
		],
		"summary": result.summary,
	}
