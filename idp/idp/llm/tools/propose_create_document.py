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
	# Phase 24 — guarantee headline totals (``total``, ``net_total``,
	# ``grand_total``, ``total_taxes_and_charges``, ``rounded_total``)
	# always show up in the header strip, even when the LLM forgot to
	# include them in the ``header`` arg.  We compute them from the
	# items / taxes block when missing so the user can review the money
	# numbers without scrolling to the totals strip.
	header_rows = _ensure_total_rows(header_rows, header, items_raw, taxes_raw)

	# Items — annotate with status (New/Existing) and fuzzy suggestions.
	items_payload = _build_items_payload(
		items_raw,
		page_size=_clamp_page_size(args.get("page_size")),
	)

	# Taxes — same treatment but always one page (rarely > 10 rows).
	taxes_payload = _build_taxes_payload(taxes_raw, company=ctx.company)

	totals = _extract_totals(header)

	summary = args.get("summary") or _default_summary(
		doctype,
		header,
		items_raw,
		taxes_raw,
		totals,
		missing_masters,
		schema_errors,
		business_rule_warnings,
	)

	card_payload: dict[str, Any] = {
		"version": CONFIRMATION_CARD_PAYLOAD_VERSION,
		"card_type": "ConfirmationCard",
		"doctype": doctype,
		"company": ctx.company,
		"file_id": file_id,
		"summary": summary,
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

	# Terminal turn: the ConfirmationCard payload already carries everything
	# the user needs to review (summary, header, items, taxes, totals,
	# validation, missing_masters, action buttons).  Set stop_processing so
	# the agent loop emits one final assistant message synthesised from
	# ``card.summary`` instead of paying for another LLM round-trip just to
	# paraphrase the card we already rendered.
	return ToolResult(
		success=True,
		data={
			"awaiting_user_confirmation": True,
			"doctype": doctype,
			"items_total": len(items_raw),
			"taxes_total": len(taxes_raw),
			"missing_master_count": len(missing_masters),
		},
		card=card_payload,
		stop_processing=True,
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
	"""Build the paginated items block (§24.2).

	Runs the §24.1 matcher in a single pass over the *full* items list
	(so even hidden pages get statuses / candidates persisted), then
	slices out the first page for the inline card payload.
	"""

	total = len(items)
	match_results = _run_item_matcher(items)

	first_page = items[:page_size]
	rows = [_build_item_row(idx, row, match_results) for idx, row in enumerate(first_page)]
	return {
		"page": 1,
		"page_size": page_size,
		"total": total,
		"has_more": total > page_size,
		"rows": rows,
	}


def _run_item_matcher(items: list[dict]) -> list[dict]:
	"""Invoke :func:`match_items` with safe fallback to per-row resolution.

	Returns a list (parallel to ``items``) of dicts with keys
	``status``, ``erpnext_item``, ``match_reason``, ``confidence``,
	``match_candidates``.  Falls back to the legacy ``_resolve_item``
	path when the matcher (or Frappe) is unavailable.
	"""

	if not items:
		return []
	try:
		from idp.idp.mappers.item_matcher import match_items as _match_items

		results = _match_items(list(items))
		return [
			{
				"status": r.status,
				"erpnext_item": r.best_match,
				"match_reason": r.match_reason,
				"confidence": r.confidence,
				"match_candidates": [c.to_dict() for c in r.matches],
			}
			for r in results
		]
	except Exception:
		out: list[dict] = []
		for row in items:
			row = row if isinstance(row, dict) else {}
			needle = (row.get("item_code") or row.get("item") or row.get("item_name") or "").strip()
			resolved, status = _resolve_item(needle)
			out.append(
				{
					"status": status,
					"erpnext_item": resolved,
					"match_reason": "exact_code" if status == "Existing" else None,
					"confidence": 1.0 if status == "Existing" else 0.0,
					"match_candidates": [],
				}
			)
		return out


def _build_item_row(idx: int, row: dict, match_results: list[dict]) -> dict:
	if not isinstance(row, dict):
		row = {}
	mr = match_results[idx] if idx < len(match_results) else {}
	status = mr.get("status") or "New"
	resolved_name = mr.get("erpnext_item")
	candidates = mr.get("match_candidates") or []

	# Backward-compat alias kept for the existing UI: emits the
	# {name, label, score} shape used since Phase 20.  The new field
	# (``match_candidates``) carries the richer §24.2 record.
	suggestions = [
		{
			"name": c.get("item_code"),
			"label": c.get("item_name"),
			"score": c.get("score"),
		}
		for c in candidates
	]

	return {
		"index": idx,
		"data": row,
		"status": status,
		"erpnext_item": resolved_name,
		"match_reason": mr.get("match_reason"),
		"confidence": mr.get("confidence"),
		"match_candidates": candidates,
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
	"""Build the per-row tax payload using the §24.3 matcher.

	Falls back to a per-row :func:`_resolve_account` lookup when the
	matcher (or Frappe) is unavailable so unit tests / CLI runs still
	produce a valid card.
	"""

	tax_results = _run_tax_matcher(taxes, company=company)

	rows: list[dict] = []
	for idx, row in enumerate(taxes):
		if not isinstance(row, dict):
			continue
		account = (row.get("account") or row.get("account_head") or "").strip()
		mr = tax_results[idx] if idx < len(tax_results) else {}
		status = mr.get("status") or "New"
		resolved = mr.get("erpnext_account")
		candidates = mr.get("match_candidates") or []

		# Backward-compat alias for the existing UI.
		suggestions = [
			{
				"name": c.get("account_name"),
				"label": c.get("display_name"),
				"score": c.get("score"),
			}
			for c in candidates
		]

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
				"match_reason": mr.get("match_reason"),
				"confidence": mr.get("confidence"),
				"match_candidates": candidates,
				"tax_mapping_suggestions": suggestions,
				"editable": True,
			}
		)
	return {"rows": rows, "total": len(rows)}


def _run_tax_matcher(taxes: list[dict], *, company: str | None) -> list[dict]:
	if not taxes:
		return []
	try:
		from idp.idp.mappers.tax_matcher import match_taxes as _match_taxes

		results = _match_taxes(list(taxes), company=company)
		return [
			{
				"status": r.status,
				"erpnext_account": r.best_match,
				"match_reason": r.match_reason,
				"confidence": r.confidence,
				"match_candidates": [c.to_dict() for c in r.matches],
			}
			for r in results
		]
	except Exception:
		out: list[dict] = []
		for row in taxes:
			row = row if isinstance(row, dict) else {}
			account = (row.get("account") or row.get("account_head") or "").strip()
			resolved, status = _resolve_account(account, company=company)
			out.append(
				{
					"status": status,
					"erpnext_account": resolved,
					"match_reason": "exact_name" if status == "Existing" else None,
					"confidence": 1.0 if status == "Existing" else 0.0,
					"match_candidates": [],
				}
			)
		return out


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


# Fields the user expects to see in the header strip alongside the
# extracted business data, in display order.  When the LLM forgets to
# include them in ``header``, we synthesise them from items/taxes.
_TOTAL_FIELDS = ("total", "net_total", "total_taxes_and_charges", "grand_total", "rounded_total")


def _coerce_amount(v: Any) -> float | None:
	if v is None or v == "":
		return None
	try:
		return float(v)
	except (TypeError, ValueError):
		return None


def _ensure_total_rows(
	header_rows: list[dict],
	header: dict,
	items: list[dict],
	taxes: list[dict],
) -> list[dict]:
	"""Append missing total fields to *header_rows* with computed values.

	Idempotent: fields already present in *header_rows* are left
	untouched.  Computed values use the items/taxes blocks so the user
	always sees a number, even when the extractor / LLM didn't ship the
	totals explicitly.
	"""

	present = {r.get("fieldname") for r in header_rows if isinstance(r, dict)}
	missing = [f for f in _TOTAL_FIELDS if f not in present]
	if not missing:
		return header_rows

	# Compute fallbacks from items/taxes so we never display a blank
	# row.  These match ERPNext's own arithmetic for the standard
	# Sales/Purchase Invoice flow.
	def _line_amount(it: dict) -> float:
		amt = _coerce_amount(it.get("amount"))
		if amt is not None:
			return amt
		qty = _coerce_amount(it.get("qty")) or 0.0
		rate = _coerce_amount(it.get("rate")) or 0.0
		return qty * rate

	items_total = sum(_line_amount(it) for it in items if isinstance(it, dict))
	tax_total = sum(_coerce_amount(t.get("tax_amount")) or 0.0 for t in taxes if isinstance(t, dict))

	derived = {
		"total": _coerce_amount(header.get("total")) or items_total,
		"net_total": _coerce_amount(header.get("net_total")) or items_total,
		"total_taxes_and_charges": (
			_coerce_amount(header.get("total_taxes_and_charges"))
			or _coerce_amount(header.get("taxes_and_charges"))
			or tax_total
		),
		"grand_total": (
			_coerce_amount(header.get("grand_total"))
			or (items_total + tax_total)
		),
		"rounded_total": (
			_coerce_amount(header.get("rounded_total"))
			or round(items_total + tax_total, 2)
		),
	}

	for fn in missing:
		val = derived.get(fn)
		if val is None:
			continue
		header_rows.append(
			{
				"fieldname": fn,
				"value": round(val, 2) if isinstance(val, float) else val,
				"confidence": None,
				"source": "computed",
				"editable": False,
			}
		)
	return header_rows


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


_PARTY_FIELDS = (
	"supplier",
	"supplier_name",
	"customer",
	"customer_name",
	"party",
	"party_name",
)
_DOC_NUMBER_FIELDS = (
	"bill_no",
	"supplier_invoice_no",
	"name",
	"invoice_number",
	"po_no",
	"reference_no",
)
_DOC_DATE_FIELDS = (
	"bill_date",
	"posting_date",
	"transaction_date",
	"invoice_date",
	"date",
)


def _first(header: dict, keys: tuple[str, ...]) -> str | None:
	for k in keys:
		v = header.get(k)
		if v not in (None, ""):
			s = str(v).strip()
			if s:
				return s
	return None


def _format_amount(value: Any, currency: str | None) -> str | None:
	if value in (None, ""):
		return None
	try:
		n = float(value)
	except (TypeError, ValueError):
		return str(value)
	formatted = f"{n:,.2f}"
	if currency:
		return f"{formatted} {currency}"
	return formatted


def _default_summary(
	doctype: str,
	header: dict,
	items: list[dict],
	taxes: list[dict],
	totals: dict,
	missing_masters: list[dict],
	schema_errors: list[str],
	business_rule_warnings: list[str],
) -> str:
	"""Deterministic, user-facing summary rendered alongside the card.

	This text is shown to the user *as the assistant's reply* — it
	replaces the LLM round-trip that previously paraphrased the card
	payload.  Keep it dense (5-7 short lines max) and fact-only.
	"""

	currency = header.get("currency") or None
	party = _first(header, _PARTY_FIELDS)
	doc_no = _first(header, _DOC_NUMBER_FIELDS)
	doc_date = _first(header, _DOC_DATE_FIELDS)

	headline = f"Prepared {doctype}"
	if party:
		headline += f" for {party}"
	if doc_no:
		headline += f" (#{doc_no})"
	if doc_date:
		headline += f" dated {doc_date}"
	headline += "."

	bullets: list[str] = []

	# Line items / taxes counts.
	count_bits: list[str] = []
	if items:
		count_bits.append(f"{len(items)} line item(s)")
	if taxes:
		count_bits.append(f"{len(taxes)} tax row(s)")
	if count_bits:
		bullets.append("Contains " + " and ".join(count_bits) + ".")

	# Totals — only show what the document actually carried.
	total_bits: list[str] = []
	net = _format_amount(totals.get("net_total"), currency)
	tax = _format_amount(totals.get("total_taxes_and_charges"), currency)
	grand = _format_amount(totals.get("grand_total"), currency)
	if net:
		total_bits.append(f"Net {net}")
	if tax:
		total_bits.append(f"Tax {tax}")
	if grand:
		total_bits.append(f"Grand Total {grand}")
	if total_bits:
		bullets.append(" | ".join(total_bits))

	# Blockers / warnings the user should notice.
	if missing_masters:
		bullets.append(
			f"{len(missing_masters)} missing master(s) need approval before submit."
		)
	if schema_errors:
		bullets.append(f"{len(schema_errors)} schema error(s) must be fixed.")
	elif business_rule_warnings:
		bullets.append(f"{len(business_rule_warnings)} validation warning(s) to review.")

	bullets.append("Review the card below and click Submit to create the record.")

	return headline + "\n\n" + "\n".join(f"- {b}" for b in bullets)


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
