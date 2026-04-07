# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Document comparison & reconciliation engine.

Compares extracted document data against existing ERPNext records,
highlights discrepancies for user review, and auto-matches records
by reference number, supplier, date, or item codes.
"""

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe.utils import flt, getdate

from idp.core.logger import get_logger
from idp.idp.mappers.base import MappedDocument, get_doctype_schema

logger = get_logger("idp.comparison")

# ---------------------------------------------------------------------------
# Comparison precision
# ---------------------------------------------------------------------------

CURRENCY_PRECISION: int = 2
FLOAT_PRECISION: int = 3
DATE_RANGE_DAYS: int = 15  # for auto-match date proximity
TOTAL_TOLERANCE_PCT: float = 5.0  # 5 % tolerance for total matching


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FieldComparison:
	"""Result of comparing a single field between document and record."""

	field: str
	label: str
	document_value: Any = None
	record_value: Any = None
	status: str = "match"  # "match" | "mismatch" | "missing"
	difference: str | None = None


@dataclass
class ItemComparison:
	"""Result of comparing a single line item between document and record."""

	item_code: str = ""
	item_name: str = ""
	field_comparisons: list[FieldComparison] = field(default_factory=list)
	status: str = "match"  # "match" | "partial_match" | "extra_in_document" | "extra_in_record"


@dataclass
class ComparisonResult:
	"""Overall result of comparing extracted data with an ERPNext record."""

	doctype: str = ""
	docname: str = ""
	matches: list[FieldComparison] = field(default_factory=list)
	discrepancies: list[FieldComparison] = field(default_factory=list)
	missing_in_document: list[str] = field(default_factory=list)
	missing_in_record: list[str] = field(default_factory=list)
	items_comparison: list[ItemComparison] = field(default_factory=list)
	summary: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compare_with_record(
	extracted_data: MappedDocument,
	doctype: str,
	docname: str,
) -> ComparisonResult:
	"""Compare extracted document data with an existing ERPNext record.

	Comparison strategy:
	1. Fetch the existing record via ``frappe.get_doc()``.
	2. Field-by-field comparison with type-aware matching:
	   - Dates: compare via ``getdate()`` (handles format differences)
	   - Currency/Float: compare with ``flt(val, precision)``
	   - Strings: case-insensitive, whitespace-trimmed
	3. Item-level comparison:
	   - Match by ``item_code`` (preferred) or by position (fallback)
	   - Per-row field comparison with individual diff reporting
	   - Report extra items in document and extra items in record
	"""
	result = ComparisonResult(doctype=doctype, docname=docname)

	# --- Fetch the existing record ---
	try:
		record = frappe.get_doc(doctype, docname)
	except frappe.DoesNotExistError:
		result.summary = f'{doctype} "{docname}" does not exist'
		return result

	schema = get_doctype_schema(doctype)
	schema_fields = schema["fields"]

	# --- Header field comparison ---
	_compare_header_fields(extracted_data, record, schema_fields, result)

	# --- Item-level comparison ---
	child_table_info = _get_primary_child_table(schema)
	if child_table_info:
		parentfield = child_table_info["parentfield"]
		child_fields = child_table_info["fields"]
		record_items = record.get(parentfield) or []
		_compare_items(extracted_data.items, record_items, child_fields, result)

	# --- Generate summary ---
	result.summary = _build_summary(result)

	logger.info(
		f"Compared {doctype} {docname}: "
		f"{len(result.matches)} match(es), {len(result.discrepancies)} discrepancy(ies)"
	)

	return result


def find_matching_record(
	extracted_data: MappedDocument,
	doctype: str = "Purchase Order",
	company: str | None = None,
) -> str | None:
	"""Attempt to find the matching ERPNext record for comparison.

	Matching strategy:
	1. Match by explicit reference number (``bill_no``, ``po_no``).
	2. Match by supplier + date range + approximate total.
	3. Match by supplier + item codes.
	4. Return ``None`` if no confident match found.
	"""
	header = extracted_data.header

	# --- 1. Match by reference number ---
	name = _match_by_reference(header, doctype)
	if name:
		return name

	# --- 2. Match by supplier + date + total ---
	name = _match_by_supplier_date_total(header, doctype, company)
	if name:
		return name

	# --- 3. Match by supplier + item codes ---
	name = _match_by_supplier_items(header, extracted_data.items, doctype, company)
	if name:
		return name

	return None


# ---------------------------------------------------------------------------
# Header field comparison
# ---------------------------------------------------------------------------


def _compare_header_fields(
	extracted_data: MappedDocument,
	record,
	schema_fields: list[dict],
	result: ComparisonResult,
) -> None:
	"""Compare header fields between extracted data and record."""
	header = extracted_data.header

	# Build a lookup of schema field metadata by fieldname
	field_meta: dict[str, dict] = {f["fieldname"]: f for f in schema_fields}

	# All fields present in either extracted data or the record
	extracted_fieldnames = set(header.keys())
	record_fieldnames = {f["fieldname"] for f in schema_fields if record.get(f["fieldname"]) is not None}

	compared = extracted_fieldnames & record_fieldnames
	only_in_document = extracted_fieldnames - record_fieldnames
	only_in_record = record_fieldnames - extracted_fieldnames

	for fieldname in compared:
		meta = field_meta.get(fieldname, {})
		label = meta.get("label", fieldname)
		fieldtype = meta.get("fieldtype", "Data")
		doc_val = header[fieldname]
		rec_val = record.get(fieldname)

		cmp = _compare_values(fieldname, label, doc_val, rec_val, fieldtype)
		if cmp.status == "match":
			result.matches.append(cmp)
		else:
			result.discrepancies.append(cmp)

	for fieldname in only_in_document:
		meta = field_meta.get(fieldname, {})
		label = meta.get("label", fieldname)
		result.missing_in_record.append(f"{label} ({fieldname})")

	for fieldname in only_in_record:
		meta = field_meta.get(fieldname, {})
		label = meta.get("label", fieldname)
		result.missing_in_document.append(f"{label} ({fieldname})")


# ---------------------------------------------------------------------------
# Value comparison (type-aware)
# ---------------------------------------------------------------------------


def _compare_values(
	fieldname: str,
	label: str,
	doc_val: Any,
	rec_val: Any,
	fieldtype: str,
) -> FieldComparison:
	"""Compare two values using type-appropriate logic."""
	if fieldtype == "Date":
		return _compare_dates(fieldname, label, doc_val, rec_val)
	elif fieldtype in ("Currency", "Float", "Percent"):
		precision = CURRENCY_PRECISION if fieldtype == "Currency" else FLOAT_PRECISION
		return _compare_numbers(fieldname, label, doc_val, rec_val, precision)
	elif fieldtype == "Int":
		return _compare_numbers(fieldname, label, doc_val, rec_val, 0)
	else:
		return _compare_strings(fieldname, label, doc_val, rec_val)


def _compare_dates(fieldname: str, label: str, doc_val: Any, rec_val: Any) -> FieldComparison:
	"""Compare date values using frappe.utils.getdate()."""
	try:
		doc_date = getdate(str(doc_val)) if doc_val else None
		rec_date = getdate(str(rec_val)) if rec_val else None
	except Exception:
		# Fall back to string comparison if date parsing fails
		return _compare_strings(fieldname, label, doc_val, rec_val)

	if doc_date == rec_date:
		return FieldComparison(
			field=fieldname, label=label, document_value=doc_val, record_value=rec_val, status="match"
		)

	return FieldComparison(
		field=fieldname,
		label=label,
		document_value=doc_val,
		record_value=rec_val,
		status="mismatch",
		difference=f"Document: {doc_date}, Record: {rec_date}",
	)


def _compare_numbers(
	fieldname: str, label: str, doc_val: Any, rec_val: Any, precision: int
) -> FieldComparison:
	"""Compare numeric values with precision-based rounding."""
	doc_num = flt(doc_val, precision)
	rec_num = flt(rec_val, precision)

	if doc_num == rec_num:
		return FieldComparison(
			field=fieldname, label=label, document_value=doc_val, record_value=rec_val, status="match"
		)

	diff = doc_num - rec_num
	return FieldComparison(
		field=fieldname,
		label=label,
		document_value=doc_val,
		record_value=rec_val,
		status="mismatch",
		difference=f"Document: {doc_num}, Record: {rec_num} (diff: {diff:+.{precision}f})",
	)


def _compare_strings(fieldname: str, label: str, doc_val: Any, rec_val: Any) -> FieldComparison:
	"""Compare string values (case-insensitive, whitespace-trimmed)."""
	doc_str = str(doc_val).strip().lower() if doc_val is not None else ""
	rec_str = str(rec_val).strip().lower() if rec_val is not None else ""

	if doc_str == rec_str:
		return FieldComparison(
			field=fieldname, label=label, document_value=doc_val, record_value=rec_val, status="match"
		)

	return FieldComparison(
		field=fieldname,
		label=label,
		document_value=doc_val,
		record_value=rec_val,
		status="mismatch",
		difference=f'Document: "{doc_val}", Record: "{rec_val}"',
	)


# ---------------------------------------------------------------------------
# Item-level comparison
# ---------------------------------------------------------------------------


def _compare_items(
	doc_items: list[dict],
	record_items: list,
	child_fields: list[dict],
	result: ComparisonResult,
) -> None:
	"""Compare line items between extracted data and record.

	Match by ``item_code`` first; fall back to positional matching.
	"""
	field_meta: dict[str, dict] = {f["fieldname"]: f for f in child_fields}

	# Build lookup of record items by item_code
	rec_by_code: dict[str, list] = {}
	for row in record_items:
		code = row.get("item_code") or ""
		rec_by_code.setdefault(code, []).append(row)

	matched_rec_indices: set[int] = set()

	for doc_row in doc_items:
		doc_code = str(doc_row.get("item_code") or "")
		doc_name = str(doc_row.get("item_name") or "")

		# Try item_code match
		matched_rec_row = None
		if doc_code and doc_code in rec_by_code:
			for rec_row in rec_by_code[doc_code]:
				idx = _get_row_idx(rec_row, record_items)
				if idx not in matched_rec_indices:
					matched_rec_row = rec_row
					matched_rec_indices.add(idx)
					break

		# Try item_name match as fallback
		if matched_rec_row is None and doc_name:
			for ri, rec_row in enumerate(record_items):
				if ri in matched_rec_indices:
					continue
				rec_name = str(rec_row.get("item_name") or "").strip().lower()
				if doc_name.strip().lower() == rec_name:
					matched_rec_row = rec_row
					matched_rec_indices.add(ri)
					break

		if matched_rec_row is not None:
			item_cmp = _compare_single_item(doc_row, matched_rec_row, field_meta)
			item_cmp.item_code = doc_code
			item_cmp.item_name = doc_name
			result.items_comparison.append(item_cmp)
		else:
			# Extra in document (no matching record row)
			result.items_comparison.append(
				ItemComparison(
					item_code=doc_code,
					item_name=doc_name,
					status="extra_in_document",
				)
			)

	# Record items that were not matched
	for ri, rec_row in enumerate(record_items):
		if ri not in matched_rec_indices:
			result.items_comparison.append(
				ItemComparison(
					item_code=str(rec_row.get("item_code") or ""),
					item_name=str(rec_row.get("item_name") or ""),
					status="extra_in_record",
				)
			)


def _compare_single_item(
	doc_row: dict,
	rec_row,
	field_meta: dict[str, dict],
) -> ItemComparison:
	"""Compare fields between a single document item row and record item row."""
	comparisons: list[FieldComparison] = []
	has_mismatch = False

	# Compare all fields present in the extracted item
	for fieldname, doc_val in doc_row.items():
		meta = field_meta.get(fieldname, {})
		label = meta.get("label", fieldname)
		fieldtype = meta.get("fieldtype", "Data")
		rec_val = rec_row.get(fieldname)

		if rec_val is None:
			continue

		cmp = _compare_values(fieldname, label, doc_val, rec_val, fieldtype)
		comparisons.append(cmp)
		if cmp.status == "mismatch":
			has_mismatch = True

	return ItemComparison(
		field_comparisons=comparisons,
		status="partial_match" if has_mismatch else "match",
	)


def _get_row_idx(row, items_list: list) -> int:
	"""Get the index of a record row in the items list."""
	for i, item in enumerate(items_list):
		if item is row:
			return i
	return -1


# ---------------------------------------------------------------------------
# Auto-match strategies
# ---------------------------------------------------------------------------


def _match_by_reference(header: dict, doctype: str) -> str | None:
	"""Match by explicit reference number (bill_no, po_no, etc.)."""
	# Reference fields that might contain the matching document's name
	ref_fields = ["bill_no", "po_no", "reference_no", "quotation_number"]

	for ref_field in ref_fields:
		ref_value = header.get(ref_field)
		if not ref_value:
			continue
		ref_str = str(ref_value).strip()
		if not ref_str:
			continue

		# Try exact name match
		if frappe.db.exists(doctype, ref_str):
			return ref_str

		# Try searching in common reference fields of the target doctype
		for search_field in ["name", "bill_no", "po_no", "supplier_quotation"]:
			try:
				name = frappe.db.get_value(doctype, {search_field: ref_str}, "name")
				if name:
					return name
			except Exception:
				continue

	return None


def _match_by_supplier_date_total(
	header: dict,
	doctype: str,
	company: str | None,
) -> str | None:
	"""Match by supplier + date range + approximate total."""
	supplier = header.get("supplier")
	if not supplier:
		return None

	posting_date = header.get("posting_date") or header.get("transaction_date")
	grand_total = header.get("grand_total")

	filters: dict = {"docstatus": ["<", 2]}  # Not cancelled

	# Supplier / party filter
	supplier_field = _get_supplier_field(doctype)
	if supplier_field:
		filters[supplier_field] = str(supplier)
	else:
		return None

	# Company filter
	if company:
		filters["company"] = company

	# Date range filter
	if posting_date:
		date_field = _get_date_field(doctype)
		if date_field:
			try:
				base_date = getdate(str(posting_date))
				from datetime import timedelta

				filters[date_field] = [
					"between",
					[
						str(base_date - timedelta(days=DATE_RANGE_DAYS)),
						str(base_date + timedelta(days=DATE_RANGE_DAYS)),
					],
				]
			except Exception:
				pass

	# Find candidates
	candidates = frappe.get_all(
		doctype,
		filters=filters,
		fields=["name", "grand_total"],
		limit=10,
		order_by="creation desc",
	)

	if not candidates:
		return None

	# If we have a grand_total, find the closest match within tolerance
	if grand_total is not None:
		target = flt(grand_total, CURRENCY_PRECISION)
		if target > 0:
			best_match = None
			best_diff = float("inf")
			for c in candidates:
				c_total = flt(c.get("grand_total"), CURRENCY_PRECISION)
				diff_pct = abs(c_total - target) / target * 100 if target else 100
				if diff_pct <= TOTAL_TOLERANCE_PCT and abs(c_total - target) < best_diff:
					best_diff = abs(c_total - target)
					best_match = c["name"]
			if best_match:
				return best_match

	# If only one candidate, return it
	if len(candidates) == 1:
		return candidates[0]["name"]

	return None


def _match_by_supplier_items(
	header: dict,
	items: list[dict],
	doctype: str,
	company: str | None,
) -> str | None:
	"""Match by supplier + item codes."""
	supplier = header.get("supplier")
	if not supplier or not items:
		return None

	# Collect item codes from extracted data
	item_codes = [str(row["item_code"]) for row in items if row.get("item_code")]
	if not item_codes:
		return None

	supplier_field = _get_supplier_field(doctype)
	if not supplier_field:
		return None

	filters: dict = {
		supplier_field: str(supplier),
		"docstatus": ["<", 2],
	}
	if company:
		filters["company"] = company

	candidates = frappe.get_all(doctype, filters=filters, pluck="name", limit=20, order_by="creation desc")

	if not candidates:
		return None

	# Score each candidate by item code overlap
	best_match = None
	best_score = 0

	for cand_name in candidates:
		try:
			cand_doc = frappe.get_doc(doctype, cand_name)
		except Exception:
			continue

		cand_items = cand_doc.get("items") or []
		cand_codes = {str(row.get("item_code") or "") for row in cand_items}

		# Jaccard-like overlap score
		overlap = len(set(item_codes) & cand_codes)
		if overlap > best_score:
			best_score = overlap
			best_match = cand_name

	# Require at least one item match
	if best_score > 0:
		return best_match

	return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_supplier_field(doctype: str) -> str | None:
	"""Return the supplier/party field name for a DocType."""
	supplier_fields = {
		"Purchase Invoice": "supplier",
		"Purchase Order": "supplier",
		"Purchase Receipt": "supplier",
		"Supplier Quotation": "supplier",
		"Sales Invoice": "customer",
		"Sales Order": "customer",
		"Delivery Note": "customer",
		"Quotation": "party_name",
		"Opportunity": "party_name",
	}
	return supplier_fields.get(doctype)


def _get_date_field(doctype: str) -> str | None:
	"""Return the primary date field name for a DocType."""
	date_fields = {
		"Purchase Invoice": "posting_date",
		"Purchase Order": "transaction_date",
		"Purchase Receipt": "posting_date",
		"Supplier Quotation": "transaction_date",
		"Sales Invoice": "posting_date",
		"Sales Order": "transaction_date",
		"Delivery Note": "posting_date",
		"Quotation": "transaction_date",
		"Opportunity": "transaction_date",
	}
	return date_fields.get(doctype)


def _get_primary_child_table(schema: dict) -> dict | None:
	"""Return the primary child table info (usually 'items')."""
	ct = schema.get("child_tables", {})
	if "items" in ct:
		return ct["items"]
	for _key, val in ct.items():
		return val
	return None


def _build_summary(result: ComparisonResult) -> str:
	"""Generate a human-readable summary of the comparison."""
	parts: list[str] = []

	total_fields = len(result.matches) + len(result.discrepancies)
	if total_fields:
		parts.append(f"{len(result.matches)}/{total_fields} header field(s) match")

	if result.discrepancies:
		disc_fields = ", ".join(d.label for d in result.discrepancies[:5])
		parts.append(f"{len(result.discrepancies)} discrepancy(ies): {disc_fields}")

	if result.missing_in_document:
		parts.append(f"{len(result.missing_in_document)} field(s) only in record")

	if result.missing_in_record:
		parts.append(f"{len(result.missing_in_record)} field(s) only in document")

	# Item summary
	item_matches = sum(1 for i in result.items_comparison if i.status == "match")
	item_partial = sum(1 for i in result.items_comparison if i.status == "partial_match")
	item_extra_doc = sum(1 for i in result.items_comparison if i.status == "extra_in_document")
	item_extra_rec = sum(1 for i in result.items_comparison if i.status == "extra_in_record")

	if result.items_comparison:
		item_parts: list[str] = []
		if item_matches:
			item_parts.append(f"{item_matches} match")
		if item_partial:
			item_parts.append(f"{item_partial} partial")
		if item_extra_doc:
			item_parts.append(f"{item_extra_doc} extra in document")
		if item_extra_rec:
			item_parts.append(f"{item_extra_rec} extra in record")
		parts.append(f"Items: {', '.join(item_parts)}")

	return "; ".join(parts) if parts else "No fields compared"
