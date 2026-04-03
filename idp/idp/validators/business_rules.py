# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Business-rules validator — applies ERPNext-specific logic to mapped data.

Checks amounts, dates, line-item totals, currency codes, and fiscal-year
status before a document is created.
"""

import frappe

from idp.core.logger import get_logger
from idp.idp.mappers.base import MappedDocument

logger = get_logger("idp.validators")

# ---------------------------------------------------------------------------
# Tolerance constants
# ---------------------------------------------------------------------------

AMOUNT_TOLERANCE: float = 1.0  # 1 unit tolerance for computed vs extracted amounts
TAX_TOLERANCE: float = 0.5  # 0.50 unit tolerance for tax calculations
QUANTITY_TOLERANCE: float = 0.001  # Fractional qty tolerance

# DocTypes that require at least one line item
_TRANSACTION_DOCTYPES: set[str] = {
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
	"Quotation",
	"Supplier Quotation",
	"Delivery Note",
	"Purchase Receipt",
}

# Date field pairs: (date_field, must_be_after_field)
_DATE_ORDER_RULES: dict[str, list[tuple[str, str]]] = {
	"Sales Invoice": [("due_date", "posting_date")],
	"Purchase Invoice": [("due_date", "posting_date")],
	"Sales Order": [("delivery_date", "transaction_date")],
	"Purchase Order": [("schedule_date", "transaction_date")],
	"Opportunity": [("expected_closing", "transaction_date")],
	"Supplier Quotation": [("valid_till", "transaction_date")],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_business_rules(mapped_data: MappedDocument, company: str = "") -> list[str]:
	"""Apply ERPNext business rules to *mapped_data*.

	Returns a list of human-readable warning/error strings.
	An empty list means all checks passed.

	Rules applied:
	- posting_date <= due_date (for invoices)
	- qty > 0 for all line items
	- rate >= 0 for all line items
	- amount approx qty x rate (within tolerance)
	- net_total approx sum of item amounts (within tolerance)
	- grand_total approx net_total + taxes (within tolerance)
	- At least one line item for transaction documents
	- Currency must be a valid currency code
	- Fiscal year must be open for posting_date
	"""
	issues: list[str] = []

	_check_date_ordering(mapped_data, issues)
	_check_line_items_present(mapped_data, issues)
	_check_line_item_values(mapped_data, issues)
	_check_amount_totals(mapped_data, issues)
	_check_currency(mapped_data, issues)
	_check_fiscal_year(mapped_data, company, issues)

	return issues


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------


def _check_date_ordering(mapped_data: MappedDocument, issues: list[str]) -> None:
	"""Ensure date fields are in the correct chronological order."""
	rules = _DATE_ORDER_RULES.get(mapped_data.doctype, [])
	header = mapped_data.header

	for later_field, earlier_field in rules:
		later_val = header.get(later_field)
		earlier_val = header.get(earlier_field)
		if not later_val or not earlier_val:
			continue

		later_str = str(later_val).strip()
		earlier_str = str(earlier_val).strip()

		if later_str < earlier_str:
			issues.append(f"{later_field} ({later_str}) is before {earlier_field} ({earlier_str})")


def _check_line_items_present(mapped_data: MappedDocument, issues: list[str]) -> None:
	"""Transaction documents must have at least one line item."""
	if mapped_data.doctype in _TRANSACTION_DOCTYPES and not mapped_data.items:
		issues.append("At least one line item is required")


def _check_line_item_values(mapped_data: MappedDocument, issues: list[str]) -> None:
	"""Validate qty, rate, and amount for each line item."""
	for idx, row in enumerate(mapped_data.items, start=1):
		# qty > 0
		qty = _to_float(row.get("qty"))
		if qty is not None and qty <= QUANTITY_TOLERANCE:
			issues.append(f"Row {idx}: qty must be greater than 0 (got {qty})")

		# rate >= 0
		rate = _to_float(row.get("rate"))
		if rate is not None and rate < 0:
			issues.append(f"Row {idx}: rate must be >= 0 (got {rate})")

		# amount ~= qty x rate
		amount = _to_float(row.get("amount"))
		if qty is not None and rate is not None and amount is not None:
			expected = qty * rate
			if abs(amount - expected) > AMOUNT_TOLERANCE:
				issues.append(f"Row {idx}: amount ({amount}) != qty ({qty}) x rate ({rate}) = {expected}")


def _check_amount_totals(mapped_data: MappedDocument, issues: list[str]) -> None:
	"""Validate net_total and grand_total against item amounts."""
	header = mapped_data.header

	# Sum of item amounts
	item_total = 0.0
	has_amounts = False
	for row in mapped_data.items:
		amt = _to_float(row.get("amount"))
		if amt is not None:
			item_total += amt
			has_amounts = True

	# net_total ≈ sum(item amounts)
	net_total = _to_float(header.get("net_total"))
	if has_amounts and net_total is not None:
		if abs(net_total - item_total) > AMOUNT_TOLERANCE:
			issues.append(f"net_total ({net_total}) does not match sum of item amounts ({item_total})")

	# grand_total ≈ net_total + taxes
	grand_total = _to_float(header.get("grand_total"))
	taxes = _to_float(header.get("total_taxes_and_charges")) or _to_float(header.get("taxes_and_charges"))

	if grand_total is not None and net_total is not None:
		if taxes is not None:
			expected_grand = net_total + taxes
			if abs(grand_total - expected_grand) > TAX_TOLERANCE:
				issues.append(
					f"grand_total ({grand_total}) != net_total ({net_total}) + taxes ({taxes}) = {expected_grand}"
				)
		else:
			# Without explicit taxes, grand_total should be >= net_total
			if grand_total < net_total - AMOUNT_TOLERANCE:
				issues.append(f"grand_total ({grand_total}) is less than net_total ({net_total})")


def _check_currency(mapped_data: MappedDocument, issues: list[str]) -> None:
	"""Validate currency is a known Currency record in ERPNext."""
	currency = mapped_data.header.get("currency")
	if not currency:
		return

	currency_str = str(currency).strip()
	if not frappe.db.exists("Currency", currency_str):
		issues.append(f'Currency "{currency_str}" does not exist in ERPNext')


def _check_fiscal_year(
	mapped_data: MappedDocument,
	company: str,
	issues: list[str],
) -> None:
	"""Warn if the posting date falls in a closed fiscal year."""
	posting_date = mapped_data.header.get("posting_date") or mapped_data.header.get("transaction_date")
	if not posting_date:
		return

	posting_str = str(posting_date).strip()

	try:
		filters = {
			"year_start_date": ["<=", posting_str],
			"year_end_date": [">=", posting_str],
			"disabled": 0,
		}
		if company:
			filters["company"] = company

		fy = frappe.get_all("Fiscal Year", filters=filters, pluck="name", limit=1)
		if not fy:
			issues.append(f"No open fiscal year found for date {posting_str}")
	except Exception:
		# Fiscal Year check is non-critical
		logger.warning(f"Could not verify fiscal year for {posting_str}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(value) -> float | None:
	"""Safely convert a value to float, returning None on failure."""
	if value is None:
		return None
	try:
		return float(value)
	except (ValueError, TypeError):
		return None
