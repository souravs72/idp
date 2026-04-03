# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Rule-based field mapping engine.

Maps extracted document content to ERPNext DocType fields using keyword
matching, regex-based value-type detection, and fuzzy link resolution —
no LLM required.
"""

import re
from typing import ClassVar

import frappe

from idp.core.logger import get_logger
from idp.idp.extractors.base import ExtractionResult
from idp.idp.mappers.base import MappedDocument, get_doctype_schema

logger = get_logger("idp.mappers")


# ---------------------------------------------------------------------------
# Field alias normalization
# ---------------------------------------------------------------------------

FIELD_ALIASES: dict[str, str] = {
	"terms_and_conditions": "terms",
	"bank_details": "remarks",
	"contact_person": "contact_display",
	"vat": "taxes",
	"gst": "taxes",
	"tax_amount": "total_taxes_and_charges",
	"subtotal": "net_total",
	"grand_total": "grand_total",
	"total_amount": "grand_total",
}

# Display-field used by Link doctypes for fuzzy matching
LINK_DISPLAY_FIELDS: dict[str, str] = {
	"Customer": "customer_name",
	"Supplier": "supplier_name",
	"Item": "item_name",
	"Employee": "employee_name",
	"Account": "account_name",
	"Cost Center": "cost_center_name",
	"Warehouse": "warehouse_name",
	"Company": "company_name",
}


class FieldMapper:
	"""Rule-based engine to map extracted text fields to a DocType schema."""

	# ------------------------------------------------------------------
	# Keyword → fieldname mappings per DocType
	# ------------------------------------------------------------------
	FIELD_KEYWORDS: ClassVar[dict[str, dict[str, list[str]]]] = {
		"Purchase Invoice": {
			"supplier": ["supplier", "vendor", "seller", "from", "bill from", "sold by"],
			"posting_date": ["date", "invoice date", "bill date", "dated", "inv date"],
			"due_date": ["due date", "payment due", "due by", "pay by"],
			"bill_no": ["invoice no", "invoice number", "bill no", "reference", "inv no", "ref no"],
			"taxes_and_charges": ["tax", "vat", "gst", "tax amount", "tax total"],
			"net_total": ["subtotal", "sub total", "net total", "net amount"],
			"grand_total": ["grand total", "total", "total amount", "amount due", "balance due"],
			"remarks": ["remarks", "notes", "memo", "comments"],
			"terms": ["terms", "terms and conditions", "payment terms"],
			"currency": ["currency"],
		},
		"Sales Invoice": {
			"customer": ["customer", "buyer", "client", "bill to", "sold to"],
			"posting_date": ["date", "invoice date", "bill date", "dated"],
			"due_date": ["due date", "payment due", "due by"],
			"po_no": ["po no", "po number", "purchase order", "your order"],
			"taxes_and_charges": ["tax", "vat", "gst", "tax amount"],
			"net_total": ["subtotal", "sub total", "net total"],
			"grand_total": ["grand total", "total", "total amount"],
			"currency": ["currency"],
		},
		"Purchase Order": {
			"supplier": ["supplier", "vendor", "seller"],
			"transaction_date": ["date", "order date", "po date", "dated"],
			"schedule_date": ["delivery date", "expected date", "required by"],
			"net_total": ["subtotal", "sub total", "net total"],
			"grand_total": ["grand total", "total", "total amount"],
			"currency": ["currency"],
		},
		"Sales Order": {
			"customer": ["customer", "buyer", "client", "bill to"],
			"transaction_date": ["date", "order date", "so date", "dated"],
			"delivery_date": ["delivery date", "ship date", "expected date"],
			"po_no": ["po no", "po number", "purchase order", "your ref"],
			"net_total": ["subtotal", "sub total", "net total"],
			"grand_total": ["grand total", "total", "total amount"],
			"currency": ["currency"],
		},
		"Quotation": {
			"party_name": ["customer", "buyer", "client", "to", "quote to"],
			"transaction_date": ["date", "quotation date", "quote date", "dated"],
			"valid_till": ["valid till", "validity", "expiry date", "valid until"],
			"net_total": ["subtotal", "sub total", "net total"],
			"grand_total": ["grand total", "total", "total amount"],
			"currency": ["currency"],
		},
		"Payment Entry": {
			"party": ["party", "customer", "supplier", "vendor", "paid to", "received from"],
			"posting_date": ["date", "payment date", "dated"],
			"paid_amount": ["amount", "paid amount", "payment amount", "total"],
			"reference_no": ["reference", "ref no", "cheque no", "check no", "utr"],
			"reference_date": ["reference date", "cheque date", "check date"],
			"mode_of_payment": ["mode", "payment mode", "method", "payment method"],
		},
		"Journal Entry": {
			"posting_date": ["date", "journal date", "entry date", "dated"],
			"cheque_no": ["reference", "ref no", "cheque no", "check no"],
			"cheque_date": ["reference date", "cheque date", "check date"],
			"total_debit": ["total debit", "debit total"],
			"total_credit": ["total credit", "credit total"],
			"remark": ["remarks", "narration", "description", "memo"],
		},
	}

	# ------------------------------------------------------------------
	# Item-level keyword mappings (shared across DocTypes)
	# ------------------------------------------------------------------
	ITEM_KEYWORDS: ClassVar[dict[str, list[str]]] = {
		"item_code": ["item code", "item no", "product code", "sku", "part no", "code"],
		"item_name": ["item", "item name", "description", "product", "particular", "particulars"],
		"qty": ["qty", "quantity", "units", "nos", "pcs"],
		"rate": ["rate", "unit price", "price", "unit cost", "cost"],
		"amount": ["amount", "total", "line total", "value", "net amount"],
		"uom": ["uom", "unit", "unit of measure"],
		"discount_percentage": ["discount", "disc", "disc %", "discount %"],
	}

	# ------------------------------------------------------------------
	# Regex patterns for value-type detection
	# ------------------------------------------------------------------
	DATE_PATTERNS: ClassVar[list[tuple[str, str]]] = [
		# ISO: 2026-04-02
		(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "YMD"),
		# DD/MM/YYYY or DD-MM-YYYY
		(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", "DMY"),
		# MM/DD/YYYY (US)
		(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", "MDY"),
		# DD-Mon-YYYY  (02-Apr-2026)
		(r"\b(\d{1,2})[/\-.\s]([A-Za-z]{3,9})[/\-.\s](\d{4})\b", "DMnY"),
		# Mon DD, YYYY  (April 02, 2026)
		(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b", "MnDY"),
		# DD/MM/YY or DD-MM-YY
		(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b", "DMy"),
	]

	CURRENCY_PATTERN: ClassVar[str] = (
		r"[₹$€£¥]?\s*[\d,]+\.?\d*|[\d.,]+\s*(?:INR|USD|EUR|GBP|JPY|Rs\.?|AUD|CAD)"
	)

	NUMBER_PATTERN: ClassVar[str] = r"^[\d,]+\.?\d*$"

	# Month name lookup for date parsing
	_MONTHS: ClassVar[dict[str, int]] = {
		"jan": 1, "january": 1, "feb": 2, "february": 2,
		"mar": 3, "march": 3, "apr": 4, "april": 4,
		"may": 5, "jun": 6, "june": 6,
		"jul": 7, "july": 7, "aug": 8, "august": 8,
		"sep": 9, "september": 9, "oct": 10, "october": 10,
		"nov": 11, "november": 11, "dec": 12, "december": 12,
	}

	# ==================================================================
	# Public API
	# ==================================================================

	def map_fields(
		self,
		extracted: ExtractionResult,
		target_doctype: str,
		company: str | None = None,
	) -> MappedDocument:
		"""Map extracted content to *target_doctype* fields.

		Strategy:
		1. Load the DocType schema.
		2. Parse text into label-value pairs.
		3. Match header fields via keyword proximity + type inference.
		4. Match line items via column-header matching.
		5. Normalise values (dates, numbers, currencies).
		6. Resolve Link fields against the database.
		"""
		schema = get_doctype_schema(target_doctype)
		result = MappedDocument(doctype=target_doctype)

		# --- Parse label-value pairs from text ---
		pairs = self._parse_label_value_pairs(extracted.text or "")

		# --- Map header fields ---
		keywords = self.FIELD_KEYWORDS.get(target_doctype, {})
		schema_fields = schema["fields"]

		for label, value in pairs:
			fieldname = self._match_header_field(label, value, schema_fields, keywords)
			if fieldname:
				normalised = self._normalise_value(value, fieldname, schema_fields)
				result.header[fieldname] = normalised
				result.confidence_scores[fieldname] = self._score_match(label, fieldname, keywords)
			else:
				result.unmapped_fields.append({"label": label, "value": value})

		# --- Map line items from tables ---
		if extracted.tables:
			child_table_info = self._find_primary_child_table(schema)
			if child_table_info:
				items = self._map_table_items(extracted.tables, child_table_info)
				result.items = items

		# --- Resolve Link fields ---
		self._resolve_links(result, schema, company)

		return result

	# ==================================================================
	# Label-value parsing
	# ==================================================================

	def _parse_label_value_pairs(self, text: str) -> list[tuple[str, str]]:
		"""Extract ``(label, value)`` pairs from freeform text.

		Looks for patterns like ``Label: Value`` or ``Label  Value``
		separated by colons, tabs, or multiple spaces.
		"""
		pairs: list[tuple[str, str]] = []
		for line in text.splitlines():
			line = line.strip()
			if not line:
				continue

			# Try colon separator first
			if ":" in line:
				parts = line.split(":", 1)
				label = parts[0].strip()
				value = parts[1].strip()
				if label and value:
					pairs.append((label, value))
					continue

			# Try tab separator
			if "\t" in line:
				parts = line.split("\t", 1)
				label = parts[0].strip()
				value = parts[1].strip()
				if label and value:
					pairs.append((label, value))
					continue

			# Try multiple spaces (≥ 3)
			match = re.match(r"^(.+?)\s{3,}(.+)$", line)
			if match:
				pairs.append((match.group(1).strip(), match.group(2).strip()))

		return pairs

	# ==================================================================
	# Header field matching
	# ==================================================================

	def _match_header_field(
		self,
		label: str,
		value: str,
		schema_fields: list[dict],
		keywords: dict[str, list[str]],
	) -> str | None:
		"""Find the best matching fieldname for a label-value pair."""
		label_lower = label.lower().strip()

		# 1. Exact keyword match
		for fieldname, kw_list in keywords.items():
			for kw in kw_list:
				if kw == label_lower or kw in label_lower:
					return fieldname

		# 2. Check field alias table
		for alias, target in FIELD_ALIASES.items():
			if alias in label_lower:
				return target

		# 3. Direct fieldname or label match from schema
		for f in schema_fields:
			if label_lower == f["fieldname"] or label_lower == (f["label"] or "").lower():
				return f["fieldname"]

		return None

	def _score_match(
		self,
		label: str,
		fieldname: str,
		keywords: dict[str, list[str]],
	) -> float:
		"""Score how confident the keyword match is (0.0-1.0)."""
		label_lower = label.lower().strip()
		kw_list = keywords.get(fieldname, [])

		# Exact match on keyword
		if label_lower in kw_list:
			return 1.0

		# Partial match
		for kw in kw_list:
			if kw in label_lower:
				return 0.8

		# Alias match
		if any(alias in label_lower for alias in FIELD_ALIASES):
			return 0.6

		return 0.5

	# ==================================================================
	# Value normalisation
	# ==================================================================

	def _normalise_value(
		self,
		value: str,
		fieldname: str,
		schema_fields: list[dict],
	) -> str | float | int | None:
		"""Normalise a raw string value based on the target field type."""
		field_type = None
		for f in schema_fields:
			if f["fieldname"] == fieldname:
				field_type = f["fieldtype"]
				break

		if not field_type:
			return value

		if field_type == "Date":
			return self._normalise_date(value) or value
		elif field_type in ("Currency", "Float"):
			return self._normalise_number(value) if self._normalise_number(value) is not None else value
		elif field_type == "Int":
			num = self._normalise_number(value)
			return int(num) if num is not None else value
		elif field_type == "Check":
			return 1 if value.lower() in ("yes", "true", "1", "checked", "✓") else 0

		return value

	def _normalise_date(self, raw: str) -> str | None:
		"""Parse a date string from 12+ formats into ``YYYY-MM-DD``."""
		raw = raw.strip()

		for pattern, fmt in self.DATE_PATTERNS:
			match = re.search(pattern, raw)
			if not match:
				continue

			try:
				if fmt == "YMD":
					y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
				elif fmt == "DMY":
					d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
				elif fmt == "MDY":
					m, d, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
					# Only treat as MDY if month > 12 would fail for DMY
					if m > 12:
						continue
				elif fmt == "DMnY":
					d = int(match.group(1))
					m = self._month_to_int(match.group(2))
					y = int(match.group(3))
				elif fmt == "MnDY":
					m = self._month_to_int(match.group(1))
					d = int(match.group(2))
					y = int(match.group(3))
				elif fmt == "DMy":
					d, m = int(match.group(1)), int(match.group(2))
					y = int(match.group(3))
					y += 2000 if y < 100 else 0
				else:
					continue

				if m is None or not (1 <= m <= 12) or not (1 <= d <= 31):
					continue
				return f"{y:04d}-{m:02d}-{d:02d}"
			except (ValueError, TypeError):
				continue

		return None

	def _normalise_number(self, raw: str) -> float | None:
		"""Strip currency symbols, commas, and spaces to produce a float."""
		if not raw:
			return None
		# Remove currency symbols and whitespace
		cleaned = re.sub(r"[₹$€£¥\s]", "", raw)
		# Remove trailing currency codes
		cleaned = re.sub(r"(INR|USD|EUR|GBP|JPY|Rs\.?|AUD|CAD)$", "", cleaned, flags=re.IGNORECASE)
		cleaned = cleaned.strip()

		if not cleaned:
			return None

		# Handle Indian / European number formats
		# 1,23,456.78  or  1,234.56 → standard float
		# 1.234,56 (European) → swap . and ,
		if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", cleaned):
			# European: dots as thousands, comma as decimal
			cleaned = cleaned.replace(".", "").replace(",", ".")
		else:
			# Remove commas used as thousands separators
			cleaned = cleaned.replace(",", "")

		try:
			return float(cleaned)
		except ValueError:
			return None

	def _month_to_int(self, name: str) -> int | None:
		"""Convert a month name or abbreviation to an integer 1-12."""
		return self._MONTHS.get(name.lower().strip())

	# ==================================================================
	# Table / line-item mapping
	# ==================================================================

	def _find_primary_child_table(self, schema: dict) -> dict | None:
		"""Find the primary child table (usually ``items``) from the schema."""
		ct = schema.get("child_tables", {})
		# Prefer "items" if it exists
		if "items" in ct:
			return ct["items"]
		# Otherwise return the first one
		for _key, val in ct.items():
			return val
		return None

	def _map_table_items(
		self,
		tables: list[list[list[str]]],
		child_table_info: dict,
	) -> list[dict]:
		"""Map table rows to child-table fields via column-header matching."""
		child_fields = child_table_info.get("fields", [])
		items: list[dict] = []

		for table in tables:
			if len(table) < 2:
				continue  # Need at least a header row + one data row

			header_row = table[0]
			col_map = self._match_column_headers(header_row, child_fields)

			if not col_map:
				continue

			for data_row in table[1:]:
				row_dict: dict = {}
				for col_idx, fieldname in col_map.items():
					if col_idx < len(data_row):
						raw_val = data_row[col_idx].strip()
						if raw_val:
							# Normalise based on field type
							normalised = self._normalise_value(raw_val, fieldname, child_fields)
							row_dict[fieldname] = normalised

				if row_dict:
					items.append(row_dict)

		return items

	def _match_column_headers(
		self,
		header_row: list[str],
		child_fields: list[dict],
	) -> dict[int, str]:
		"""Match column headers to child-table field names.

		Returns ``{column_index: fieldname}``.
		"""
		col_map: dict[int, str] = {}

		for col_idx, header in enumerate(header_row):
			header_lower = header.lower().strip()
			if not header_lower:
				continue

			# 1. Try item keyword table
			for fieldname, kw_list in self.ITEM_KEYWORDS.items():
				if any(kw == header_lower or kw in header_lower for kw in kw_list):
					# Verify this fieldname exists in the child schema
					if any(f["fieldname"] == fieldname for f in child_fields):
						col_map[col_idx] = fieldname
						break

			# 2. Direct label / fieldname match
			if col_idx not in col_map:
				for f in child_fields:
					if header_lower == f["fieldname"] or header_lower == (f["label"] or "").lower():
						col_map[col_idx] = f["fieldname"]
						break

		return col_map

	# ==================================================================
	# Link field resolution
	# ==================================================================

	def _resolve_links(
		self,
		result: MappedDocument,
		schema: dict,
		company: str | None,
	) -> None:
		"""Attempt to resolve all Link-type header fields to existing records."""
		for f in schema["fields"]:
			if f["fieldtype"] != "Link":
				continue
			fieldname = f["fieldname"]
			if fieldname not in result.header:
				continue

			raw_value = str(result.header[fieldname])
			link_doctype = f["options"]
			if not link_doctype:
				continue

			resolved = self._resolve_link(raw_value, link_doctype, company)
			if resolved and resolved != raw_value:
				result.link_resolutions[fieldname] = {
					"original": raw_value,
					"resolved": resolved,
				}
				result.header[fieldname] = resolved
			elif not resolved:
				result.warnings.append(
					f'{link_doctype} "{raw_value}" not found (field: {fieldname})'
				)

	def _resolve_link(
		self,
		value: str,
		doctype: str,
		company: str | None = None,
	) -> str | None:
		"""Fuzzy-match *value* to an existing record of *doctype*.

		Resolution order:
		1. Exact match on ``name``.
		2. Exact match on display field (customer_name, supplier_name …).
		3. ``LIKE`` match on display field (must be unique).
		4. Company-scoped search.
		"""
		if not value:
			return None

		# 1. Exact name
		if frappe.db.exists(doctype, value):
			return value

		# 2. Exact display-field match
		display_field = LINK_DISPLAY_FIELDS.get(doctype)
		if display_field:
			match = frappe.db.get_value(
				doctype,
				{display_field: value},
				"name",
			)
			if match:
				return match

		# 3. LIKE match on display field
		if display_field:
			filters = {display_field: ["like", f"%{value}%"]}
			if company and _has_company_field(doctype):
				filters["company"] = company
			matches = frappe.get_all(doctype, filters=filters, pluck="name", limit=2)
			if len(matches) == 1:
				return matches[0]

		return None


def _has_company_field(doctype: str) -> bool:
	"""Check whether *doctype* has a ``company`` field."""
	try:
		meta = frappe.get_meta(doctype)
		return meta.has_field("company")
	except Exception:
		return False
