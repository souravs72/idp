# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``propose_create_document`` — render the Phase 20 ConfirmationCard.

Non-mutating: never inserts the ERPNext document.  It builds the rich
card payload (per-field provenance, items + taxes with status, totals,
validation, pagination, missing-master prerequisites, action buttons)
that the chatbot UI renders so the user can review, edit, and confirm
before ``create_document`` runs.

Card payload shape (versioned by
:data:`idp.idp.llm.schemas.CONFIRMATION_CARD_PAYLOAD_VERSION`)::

    {
      "version": 1,
      "card_type": "ConfirmationCard",
      "doctype": "Purchase Invoice",
      "company": "Acme",
      "file_id": "file_1",
      "summary": "...",
      "header": [
         {"fieldname": "supplier", "value": "...", "confidence": 0.92,
          "source": "rule" | "llm" | "template", "editable": True}, ...
      ],
      "items": {
         "page": 1, "page_size": 10, "total": 23,
         "rows": [
            {"index": 0, "data": {...}, "status": "Existing"|"New",
             "erpnext_item": "ITEM-0001",
             "item_mapping_suggestions": [{name, label, score}], ...},
            ...
         ]
      },
      "taxes": {
         "rows": [
            {"row_index": 0,
             "extracted": {"account": "IGST", "rate": 0.18, "tax_amount": 1800},
             "erpnext_account": "IGST - ACME",
             "status": "Existing" | "New",
             "tax_mapping_suggestions": [{name, label, score}, ...]}
         ]
      },
      "totals": {"net_total": ..., "total_taxes_and_charges": ..., "grand_total": ...},
      "validation": {"schema_errors": [...], "schema_warnings": [...],
                     "business_rule_warnings": [...]},
      "missing_masters": [{...}, ...],
      "actions": [{"id": "submit", "label": "Submit", "primary": True}, ...]
    }
"""

from __future__ import annotations

from typing import Any

from idp.idp.llm.schemas import CONFIRMATION_CARD_PAYLOAD_VERSION
from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

_DEFAULT_PAGE_SIZE = 10
_MAX_PAGE_SIZE = 100


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "Target ERPNext DocType."},
		"header": {
			"type": "object",
			"description": "Field name → value map for the parent doc.",
			"additionalProperties": True,
		},
		"items": {
			"type": "array",
			"description": "Optional child-table rows.",
			"items": {"type": "object", "additionalProperties": True},
		},
		"taxes": {
			"type": "array",
			"description": (
				"Per-row tax breakdown (Phase 20).  Each entry is "
				"``{account, rate, tax_amount, taxable_amount?, description?}``."
			),
			"items": {"type": "object", "additionalProperties": True},
		},
		"file_id": {
			"type": "string",
			"description": "Source attachment alias (file_1, file_2, ...) for provenance.",
		},
		"confidence_scores": {
			"type": "object",
			"description": (
				"Per-field confidence scores from the mapper.  Values may be a float "
				"or an object {score, source} carrying provenance."
			),
			"additionalProperties": True,
		},
		"warnings": {
			"type": "array",
			"description": "Validator warnings to surface alongside the fields.",
			"items": {"type": "string"},
		},
		"schema_errors": {
			"type": "array",
			"description": "Hard schema validation errors.",
			"items": {"type": "string"},
		},
		"missing_masters": {
			"type": "array",
			"description": "List of {doctype, name, ...} that need creation first.",
			"items": {"type": "object", "additionalProperties": True},
		},
		"summary": {
			"type": "string",
			"description": "Short user-facing summary of what is about to be created.",
		},
		"page_size": {
			"type": "integer",
			"description": "Items page size (default 10, max 100).",
			"minimum": 1,
			"maximum": _MAX_PAGE_SIZE,
		},
	},
	"required": ["doctype", "header"],
	"additionalProperties": False,
}


@tool(
	name="propose_create_document",
	description=(
		"Render a ConfirmationCard to the user with the extracted fields, "
		"per-row taxes (with editable account suggestions), warnings, and "
		"missing prerequisites.  This does NOT create the ERPNext document — "
		"the user must explicitly confirm in the UI before create_document is "
		"called.  Always call this before create_document."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def propose_create_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	header = args.get("header") or {}
	if not isinstance(header, dict) or not header:
		return ToolResult.fail(
			"header object with at least one field is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	items_raw: list[dict] = list(args.get("items") or [])
	taxes_raw: list[dict] = list(args.get("taxes") or [])
	confidence_scores: dict = args.get("confidence_scores") or {}
	warnings: list[str] = list(args.get("warnings") or [])
	schema_errors: list[str] = list(args.get("schema_errors") or [])
	missing_masters: list[dict] = list(args.get("missing_masters") or [])
	file_id = args.get("file_id")

	# Run business-rule validation on a synthesised MappedDocument so the
	# card carries the same warnings the eventual create_document call
	# will produce.
	business_rule_warnings = _run_business_rules(doctype, header, items_raw, taxes_raw, ctx.company)

	# Header — emit as ordered list with provenance.
	header_rows = _build_header_rows(header, confidence_scores)

	# Items — annotate with status (New/Existing) and fuzzy suggestions.
	items_payload = _build_items_payload(
		items_raw,
		page_size=_clamp_page_size(args.get("page_size")),
	)

	# Taxes — same treatment but always one page (rarely > 10 rows).
	taxes_payload = _build_taxes_payload(taxes_raw, company=ctx.company)

	totals = _extract_totals(header)

	card_payload: dict[str, Any] = {
		"version": CONFIRMATION_CARD_PAYLOAD_VERSION,
		"card_type": "ConfirmationCard",
		"doctype": doctype,
		"company": ctx.company,
		"file_id": file_id,
		"summary": args.get("summary") or _default_summary(doctype, items_raw, taxes_raw),
		"header": header_rows,
		"items": items_payload,
		"taxes": taxes_payload,
		"totals": totals,
		"validation": {
			"schema_errors": schema_errors,
			"schema_warnings": warnings,
			"business_rule_warnings": business_rule_warnings,
		},
		"missing_masters": missing_masters,
		"actions": _default_actions(missing_masters, schema_errors),
	}

	return ToolResult.ok(
		data={
			"awaiting_user_confirmation": True,
			"doctype": doctype,
			"items_total": len(items_raw),
			"taxes_total": len(taxes_raw),
			"missing_master_count": len(missing_masters),
		},
		card=card_payload,
	)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _build_header_rows(header: dict, confidence_scores: dict) -> list[dict]:
	rows: list[dict] = []
	for fieldname, value in header.items():
		conf, source = _split_confidence(confidence_scores.get(fieldname))
		rows.append(
			{
				"fieldname": fieldname,
				"value": value,
				"confidence": conf,
				"source": source,
				"editable": True,
			}
		)
	return rows


def _split_confidence(entry: Any) -> tuple[float | None, str | None]:
	if entry is None:
		return None, None
	if isinstance(entry, dict):
		score = entry.get("score")
		try:
			score_f = float(score) if score is not None else None
		except (TypeError, ValueError):
			score_f = None
		return score_f, entry.get("source")
	try:
		return float(entry), None
	except (TypeError, ValueError):
		return None, None


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def _build_items_payload(items: list[dict], *, page_size: int) -> dict:
	total = len(items)
	first_page = items[:page_size]
	rows = [_build_item_row(idx, row) for idx, row in enumerate(first_page)]
	return {
		"page": 1,
		"page_size": page_size,
		"total": total,
		"has_more": total > page_size,
		"rows": rows,
	}


def _build_item_row(idx: int, row: dict) -> dict:
	if not isinstance(row, dict):
		row = {}
	item_code = (row.get("item_code") or row.get("item") or row.get("item_name") or "").strip()
	resolved_name, status = _resolve_item(item_code)
	suggestions: list[dict] = []
	if status == "New" and item_code:
		try:
			from idp.idp.mappers.fuzzy_match import suggest_item

			suggestions = suggest_item(item_code, top_n=5)
		except Exception:
			suggestions = []
	return {
		"index": idx,
		"data": row,
		"status": status,
		"erpnext_item": resolved_name,
		"item_mapping_suggestions": suggestions,
	}


def _resolve_item(item_code: str) -> tuple[str | None, str]:
	if not item_code:
		return None, "New"
	try:
		import frappe
	except ImportError:
		return None, "New"
	try:
		if frappe.db.exists("Item", item_code):
			return item_code, "Existing"
		# Try matching on item_name as well.
		row = frappe.db.get_value("Item", {"item_name": item_code}, "name")
		if row:
			return str(row), "Existing"
	except Exception:
		pass
	return None, "New"


# ---------------------------------------------------------------------------
# Taxes
# ---------------------------------------------------------------------------


def _build_taxes_payload(taxes: list[dict], *, company: str | None) -> dict:
	rows: list[dict] = []
	for idx, row in enumerate(taxes):
		if not isinstance(row, dict):
			continue
		account = (row.get("account") or row.get("account_head") or "").strip()
		resolved, status = _resolve_account(account, company=company)
		suggestions: list[dict] = []
		if status == "New" and account:
			try:
				from idp.idp.mappers.fuzzy_match import suggest_account

				suggestions = suggest_account(account, company=company, top_n=5)
			except Exception:
				suggestions = []
		rows.append(
			{
				"row_index": idx,
				"extracted": {
					"account": account,
					"rate": row.get("rate"),
					"tax_amount": row.get("tax_amount") or row.get("amount"),
					"taxable_amount": row.get("taxable_amount") or row.get("base"),
					"description": row.get("description"),
				},
				"erpnext_account": resolved,
				"status": status,
				"tax_mapping_suggestions": suggestions,
				"editable": True,
			}
		)
	return {"rows": rows, "total": len(rows)}


def _resolve_account(account: str, *, company: str | None) -> tuple[str | None, str]:
	if not account:
		return None, "New"
	try:
		import frappe
	except ImportError:
		return None, "New"
	try:
		if frappe.db.exists("Account", account):
			return account, "Existing"
		filters: dict[str, Any] = {"account_name": account}
		if company:
			filters["company"] = company
		row = frappe.db.get_value("Account", filters, "name")
		if row:
			return str(row), "Existing"
	except Exception:
		pass
	return None, "New"


# ---------------------------------------------------------------------------
# Totals & validation
# ---------------------------------------------------------------------------


def _extract_totals(header: dict) -> dict:
	return {
		"net_total": header.get("net_total"),
		"total_taxes_and_charges": (header.get("total_taxes_and_charges") or header.get("taxes_and_charges")),
		"grand_total": header.get("grand_total"),
		"rounded_total": header.get("rounded_total"),
	}


def _run_business_rules(
	doctype: str,
	header: dict,
	items: list[dict],
	taxes: list[dict],
	company: str | None,
) -> list[str]:
	"""Run the business-rules validator on a synthesised MappedDocument.

	Failures here never abort the card render — we just append the
	warnings to ``validation.business_rule_warnings``.
	"""

	try:
		from idp.idp.mappers.base import MappedDocument
		from idp.idp.validators.business_rules import validate_business_rules
	except Exception:
		return []
	try:
		mapped = MappedDocument(
			doctype=doctype,
			header=dict(header),
			items=list(items),
			taxes=list(taxes),
		)
		return validate_business_rules(mapped, company or "")
	except Exception:
		return []


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _clamp_page_size(value: Any) -> int:
	try:
		v = int(value) if value is not None else _DEFAULT_PAGE_SIZE
	except (TypeError, ValueError):
		v = _DEFAULT_PAGE_SIZE
	return max(1, min(v, _MAX_PAGE_SIZE))


def _default_summary(doctype: str, items: list[dict], taxes: list[dict]) -> str:
	parts = [f"Review the proposed {doctype}"]
	if items:
		parts.append(f"with {len(items)} line item(s)")
	if taxes:
		parts.append(f"and {len(taxes)} tax row(s)")
	parts.append("below before confirming.")
	return " ".join(parts)


def _default_actions(missing_masters: list[dict], schema_errors: list[str]) -> list[dict]:
	# Submit is disabled (advisory only — UI enforces) when blockers exist.
	blocked = bool(missing_masters) or bool(schema_errors)
	return [
		{"id": "submit", "label": "Submit", "primary": True, "disabled": blocked},
		{"id": "save_draft", "label": "Save as Draft", "primary": False, "disabled": False},
		{"id": "edit", "label": "Edit", "primary": False, "disabled": False},
		{"id": "cancel", "label": "Cancel", "primary": False, "disabled": False},
	]


__all__ = ["propose_create_document"]
