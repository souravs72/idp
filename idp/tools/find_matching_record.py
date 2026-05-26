# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``find_matching_record`` — locate a candidate ERPNext record.

Used during the *compare* flow: given the extracted header from a
file (e.g. an invoice), the LLM asks the server for the most likely
existing record (e.g. by ``bill_no`` + ``supplier``) so it can render
a ComparisonCard.  Returns up to ``limit`` candidates with a coarse
score, the LLM picks the best match (or asks the user).
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 25

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType to search."},
		"filters": {
			"type": "object",
			"description": "Equality filters (fieldname → value).",
			"additionalProperties": True,
		},
		"or_filters": {
			"type": "object",
			"description": "Optional OR equality filters.",
			"additionalProperties": True,
		},
		"fields": {
			"type": "array",
			"description": "Fields to return on each candidate.",
			"items": {"type": "string"},
		},
		"limit": {
			"type": "integer",
			"minimum": 1,
			"maximum": _MAX_LIMIT,
			"description": f"Max candidates to return (default {_DEFAULT_LIMIT}).",
		},
	},
	"required": ["doctype", "filters"],
	"additionalProperties": False,
}


@tool(
	name="find_matching_record",
	description=(
		"Find candidate ERPNext records matching the given filters (e.g. by "
		"bill_no and supplier).  Returns up to N candidates with the requested "
		"fields.  Use this before compare_document when matching a file to an "
		"existing record."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def find_matching_record(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	filters = args.get("filters") or {}
	or_filters = args.get("or_filters") or {}
	if not isinstance(filters, dict) or not isinstance(or_filters, dict):
		return ToolResult.fail(
			"filters/or_filters must be objects",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not filters and not or_filters:
		return ToolResult.fail(
			"at least one filter is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	fields = args.get("fields") or ["name"]
	if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
		return ToolResult.fail(
			"fields must be a list of strings",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	# Always include "name" so the LLM can reference the candidate downstream.
	if "name" not in fields:
		fields = ["name", *fields]

	limit = args.get("limit") or _DEFAULT_LIMIT
	try:
		limit = max(1, min(int(limit), _MAX_LIMIT))
	except (TypeError, ValueError):
		limit = _DEFAULT_LIMIT

	publish_progress(
		ctx,
		tool_name="find_matching_record",
		user_visible_message=f"Searching for matching {doctype} records…",
		stage="search_start",
	)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	# Permission gate — frappe.get_list honours user permissions.
	try:
		rows: list[dict[str, Any]] = frappe.get_list(
			doctype,
			filters=filters,
			or_filters=or_filters or None,
			fields=fields,
			limit_page_length=limit,
			user=ctx.user,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"count": len(rows),
			"candidates": rows,
		}
	)


__all__ = ["find_matching_record"]
