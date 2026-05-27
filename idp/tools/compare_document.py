# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``compare_document`` — diff a file alias against an existing ERPNext record.

Loads the existing record, walks the LLM-supplied ``proposed`` map,
and returns per-field differences classified as match / mismatch /
missing.  The chatbot UI renders this as a ComparisonCard so the user
can decide whether to update the existing record or create a new one.

When ``name`` is omitted the tool runs an internal find first (using
the supplied ``filters``) and auto-selects the single candidate, saving
a round-trip.  If multiple candidates are found they are returned as a
``candidates`` list so the LLM can pick one and call again with ``name``.

Comparison is *non-mutating* — it only reports differences.
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 25

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType."},
		"name": {
			"type": "string",
			"description": (
				"Existing record's name (primary key). "
				"If omitted, supply filters so the tool can locate the record internally."
			),
		},
		"proposed": {
			"type": "object",
			"description": "Fieldname → expected-value map extracted from the file.",
			"additionalProperties": True,
		},
		"file_id": {
			"type": "string",
			"description": "Source attachment alias for provenance on the card.",
		},
		"items": {
			"type": "array",
			"description": "Optional child rows to diff against the record's items child table.",
			"items": {"type": "object", "additionalProperties": True},
		},
		"items_fieldname": {
			"type": "string",
			"description": "Child-table fieldname (default 'items').",
		},
		# Auto-find params (used when name is omitted)
		"filters": {
			"type": "object",
			"description": "Equality filters used to locate the record when name is not supplied (e.g. {bill_no: 'INV-42', supplier: 'Acme'}).",
			"additionalProperties": True,
		},
		"or_filters": {
			"type": "object",
			"description": "Optional OR equality filters for the internal find.",
			"additionalProperties": True,
		},
		"fields": {
			"type": "array",
			"description": "Fields to include on each candidate row when multiple matches are found.",
			"items": {"type": "string"},
		},
		"limit": {
			"type": "integer",
			"minimum": 1,
			"maximum": _MAX_LIMIT,
			"description": f"Max candidates to return when multiple matches are found (default {_DEFAULT_LIMIT}).",
		},
	},
	"required": ["doctype", "proposed"],
	"additionalProperties": False,
}


@tool(
	name="compare_document",
	description=(
		"Diff a proposed mapping (extracted from a file) against an existing "
		"ERPNext record.  Returns per-field match/mismatch/missing classification "
		"and a ComparisonCard payload for the UI.  "
		"Supply name to compare directly, or supply filters to let the tool "
		"locate the record automatically (saves a round-trip).  "
		"If multiple candidates are found they are returned so the LLM can pick one."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def compare_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	proposed = args.get("proposed") or {}

	if not doctype:
		return ToolResult.fail("doctype is required", error_code="MISSING_ARGUMENT", stop_processing=False)
	if not isinstance(proposed, dict) or not proposed:
		return ToolResult.fail("proposed object is required", error_code="MISSING_ARGUMENT", stop_processing=False)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail("frappe runtime not available", error_code="UNEXPECTED_ERROR", stop_processing=True)

	# Auto-find: when name is absent, locate the record using filters.
	if not name:
		filters = args.get("filters") or {}
		or_filters = args.get("or_filters") or {}
		if not filters and not or_filters:
			return ToolResult.fail(
				"either name or filters is required",
				error_code="MISSING_ARGUMENT",
				stop_processing=False,
			)
		find_result = _find_candidate(doctype, filters, or_filters, args, ctx, frappe)
		if not find_result["success"]:
			return ToolResult.fail(
				find_result["error"],
				error_code=find_result.get("error_code", "RECORD_NOT_FOUND"),
				stop_processing=False,
			)
		candidates = find_result["candidates"]
		if len(candidates) == 0:
			return ToolResult.fail(
				f"no {doctype} record matched the supplied filters",
				error_code="RECORD_NOT_FOUND",
				stop_processing=False,
			)
		if len(candidates) > 1:
			# Return the list so the LLM can pick one and call again with name.
			return ToolResult.ok(
				data={
					"doctype": doctype,
					"candidates": candidates,
					"count": len(candidates),
					"message": (
						f"Found {len(candidates)} candidates. "
						"Call compare_document again with name=<chosen record name>."
					),
				}
			)
		name = candidates[0].get("name", "")
		if not name:
			return ToolResult.fail(
				"auto-find returned a candidate without a name field",
				error_code="UNEXPECTED_ERROR",
				stop_processing=False,
			)

	publish_progress(
		ctx,
		tool_name="compare_document",
		user_visible_message=f"Comparing against existing {doctype} {name}…",
		stage="compare_start",
	)

	try:
		existing = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:  # type: ignore[attr-defined]
		return ToolResult.fail(f"{doctype} {name!r} not found", error_code="RECORD_NOT_FOUND", stop_processing=False)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(str(exc) or "permission denied", error_code="PERMISSION_DENIED", stop_processing=True)

	differences: list[dict] = []
	for fieldname, expected in proposed.items():
		actual = existing.get(fieldname) if hasattr(existing, "get") else None
		differences.append(
			{
				"fieldname": fieldname,
				"expected": expected,
				"actual": actual,
				"status": _classify(expected, actual),
			}
		)

	item_diffs: list[dict] = []
	items = args.get("items") or []
	items_fieldname = (args.get("items_fieldname") or "items").strip() or "items"
	if isinstance(items, list) and items:
		actual_rows = existing.get(items_fieldname) or []
		for idx, expected_row in enumerate(items):
			actual_row = (
				actual_rows[idx].as_dict()
				if idx < len(actual_rows) and hasattr(actual_rows[idx], "as_dict")
				else (actual_rows[idx] if idx < len(actual_rows) else {})
			)
			row_diff: dict[str, Any] = {"index": idx, "fields": []}
			for fieldname, expected in (expected_row or {}).items():
				actual = (actual_row or {}).get(fieldname)
				row_diff["fields"].append(
					{
						"fieldname": fieldname,
						"expected": expected,
						"actual": actual,
						"status": _classify(expected, actual),
					}
				)
			item_diffs.append(row_diff)

	mismatch_count = sum(1 for d in differences if d["status"] == "mismatch")
	missing_count = sum(1 for d in differences if d["status"] == "missing")

	card_payload = {
		"card_type": "ComparisonCard",
		"doctype": doctype,
		"name": name,
		"file_id": args.get("file_id"),
		"differences": differences,
		"item_differences": item_diffs,
		"summary": (
			f"Compared {doctype} {name}: {mismatch_count} mismatch(es), {missing_count} missing field(s)."
		),
	}

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"name": name,
			"differences": differences,
			"item_differences": item_diffs,
			"mismatch_count": mismatch_count,
			"missing_count": missing_count,
		},
		card=card_payload,
	)


def _find_candidate(
	doctype: str,
	filters: dict,
	or_filters: dict,
	args: dict,
	ctx: ToolContext,
	frappe: Any,
) -> dict:
	publish_progress(
		ctx,
		tool_name="compare_document",
		user_visible_message=f"Searching for matching {doctype} records…",
		stage="find_start",
	)

	fields = args.get("fields") or ["name"]
	if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
		fields = ["name"]
	if "name" not in fields:
		fields = ["name", *fields]

	limit = args.get("limit") or _DEFAULT_LIMIT
	try:
		limit = max(1, min(int(limit), _MAX_LIMIT))
	except (TypeError, ValueError):
		limit = _DEFAULT_LIMIT

	try:
		rows = frappe.get_list(
			doctype,
			filters=filters,
			or_filters=or_filters or None,
			fields=fields,
			limit_page_length=limit,
			user=ctx.user,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return {"success": False, "error": str(exc) or "permission denied", "error_code": "PERMISSION_DENIED"}

	return {"success": True, "candidates": rows}


def _classify(expected: Any, actual: Any) -> str:
	if expected is None or expected == "":
		return "missing"
	if actual is None or actual == "":
		return "missing"
	if _normalize(expected) == _normalize(actual):
		return "match"
	return "mismatch"


def _normalize(v: Any) -> Any:
	if isinstance(v, str):
		return v.strip().casefold()
	if isinstance(v, float):
		return round(v, 2)
	return v


__all__ = ["compare_document"]
