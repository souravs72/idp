# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Compatibility shim — ``find_matching_record`` is no longer an LLM-exposed tool.

The find logic is now built into ``compare_document`` (supply ``filters``
and omit ``name``).  This module is retained so existing Python call-sites
(e.g. ``idp/comparison/engine.py``) are not broken.
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 25


def find_matching_record(arguments: dict, ctx: ToolContext) -> ToolResult:
	"""Find candidate ERPNext records matching the given filters.

	Kept as a Python-callable shim.  No longer registered as an LLM tool
	— use compare_document with filters instead.
	"""
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	if not doctype:
		return ToolResult.fail("doctype is required", error_code="MISSING_ARGUMENT", stop_processing=False)

	filters = args.get("filters") or {}
	or_filters = args.get("or_filters") or {}
	if not isinstance(filters, dict) or not isinstance(or_filters, dict):
		return ToolResult.fail("filters/or_filters must be objects", error_code="MISSING_ARGUMENT", stop_processing=False)
	if not filters and not or_filters:
		return ToolResult.fail("at least one filter is required", error_code="MISSING_ARGUMENT", stop_processing=False)

	fields = args.get("fields") or ["name"]
	if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
		return ToolResult.fail("fields must be a list of strings", error_code="MISSING_ARGUMENT", stop_processing=False)
	if "name" not in fields:
		fields = ["name", *fields]

	limit = args.get("limit") or _DEFAULT_LIMIT
	try:
		limit = max(1, min(int(limit), _MAX_LIMIT))
	except (TypeError, ValueError):
		limit = _DEFAULT_LIMIT

	publish_progress(ctx, tool_name="compare_document", user_visible_message=f"Searching for matching {doctype} records…", stage="search_start")

	try:
		import frappe
	except ImportError:
		return ToolResult.fail("frappe runtime not available", error_code="UNEXPECTED_ERROR", stop_processing=True)

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
		return ToolResult.fail(str(exc) or "permission denied", error_code="PERMISSION_DENIED", stop_processing=True)

	return ToolResult.ok(data={"doctype": doctype, "count": len(rows), "candidates": rows})


__all__ = ["find_matching_record"]
