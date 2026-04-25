# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``compare_document`` — diff a file alias against an existing ERPNext record.

Loads the existing record, walks the LLM-supplied ``proposed`` map,
and returns per-field differences classified as match / mismatch /
missing.  The chatbot UI renders this as a ComparisonCard so the user
can decide whether to update the existing record or create a new one.

Comparison is *non-mutating* — it only reports differences.
"""

from __future__ import annotations

from typing import Any

from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType."},
		"name": {"type": "string", "description": "Existing record's name (primary key)."},
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
	},
	"required": ["doctype", "name", "proposed"],
	"additionalProperties": False,
}


@tool(
	name="compare_document",
	description=(
		"Diff a proposed mapping (extracted from a file) against an existing "
		"ERPNext record.  Returns per-field match/mismatch/missing classification "
		"and a ComparisonCard payload for the UI.  Use after find_matching_record "
		"locates the candidate."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def compare_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	proposed = args.get("proposed") or {}
	if not doctype or not name:
		return ToolResult.fail(
			"doctype and name are required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not isinstance(proposed, dict) or not proposed:
		return ToolResult.fail(
			"proposed object is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	try:
		existing = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:  # type: ignore[attr-defined]
		return ToolResult.fail(
			f"{doctype} {name!r} not found",
			error_code="RECORD_NOT_FOUND",
			stop_processing=False,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

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

	# Optional items diff: positional, length-aware.
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
		# Currency comparisons within 1 cent.
		return round(v, 2)
	return v


__all__ = ["compare_document"]
