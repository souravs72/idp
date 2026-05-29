# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``search_documents`` — read-only DocType search wrapping ``frappe.db.get_list``.

Closes the read-write hole on the chat surface for *finding* existing
records.  The tool is deliberately narrow:

* Per-doctype only — refuses sensitive cross-doctype enumerations
  (``User``, ``OAuth*``, ``Has Role`` …).
* Caller's ``read`` permission is checked at the DocType level and
  ``frappe.db.get_list`` is invoked with ``user=ctx.user`` so row-level
  permissions apply.
* Projection capped at 20 columns; ``limit`` capped at 50.
* Output trimmed by the registry's existing ``max_output_tokens``
  budget — overflow surfaces as ``truncated: true``.
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50
_MAX_FIELDS = 20

# Doctypes the LLM is never permitted to enumerate via this tool — even
# when the caller is a System Manager.  These are either identity
# surfaces, permission tables, or schema metadata where a wide scan
# would leak sensitive structure regardless of row-level grants.
_DOCTYPE_DENY_LIST = frozenset(
	{
		"User",
		"User Permission",
		"Has Role",
		"DocPerm",
		"Custom DocPerm",
		"Role Permission Manager",
		"OAuth Client",
		"OAuth Authorization Code",
		"OAuth Bearer Token",
		"OAuth Provider Settings",
		"Token Cache",
		"Personal Data Deletion Request",
		"Personal Data Download Request",
	}
)

_DENY_PREFIXES = ("OAuth ", "Custom ")


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {
			"type": "string",
			"description": "ERPNext DocType to query (e.g. 'Purchase Invoice').",
		},
		"filters": {
			"type": "object",
			"description": (
				"Equality filter map passed to frappe.db.get_list "
				"(e.g. {supplier: 'Acme', docstatus: 1})."
			),
			"additionalProperties": True,
		},
		"or_filters": {
			"type": "object",
			"description": "Optional OR equality filters.",
			"additionalProperties": True,
		},
		"fields": {
			"type": "array",
			"description": (
				"Projection columns.  Defaults to ['name'].  Capped at "
				f"{_MAX_FIELDS} columns."
			),
			"items": {"type": "string"},
		},
		"limit": {
			"type": "integer",
			"minimum": 1,
			"maximum": _MAX_LIMIT,
			"description": f"Max rows to return (default {_DEFAULT_LIMIT}, hard cap {_MAX_LIMIT}).",
		},
		"order_by": {
			"type": "string",
			"description": "Sort clause (default 'modified desc').",
		},
	},
	"required": ["doctype"],
	"additionalProperties": False,
}


@tool(
	name="search_documents",
	description=(
		"Search existing ERPNext records for the given doctype with filters and "
		"projection.  Read-only — never mutates.  Call this ONLY when (a) the "
		"USER has directly asked to find/list/show records by name or filter, "
		"or (b) you are recovering from an update_document AMBIGUOUS_LINK / "
		"LINK_NOT_FOUND error envelope.  Do NOT call this during an "
		"extract → propose_create_document flow to look up missing tax "
		"accounts, item masters, or supplier/customer records — that path "
		"belongs on the ConfirmationCard's inline pickers; reaching for "
		"search here breaks the create workflow.  Do NOT call this just to "
		"look up a Link's canonical name before update_document either — "
		"update_document auto-resolves human-readable values (e.g. "
		"cost_center='Test' → 'Test - TTD') scoped to the parent doc's "
		"company.  Honours row-level read permissions; refuses identity / "
		"permission doctypes.  Defaults to excluding is_group=1 rows on "
		"tree doctypes (Cost Center, Account, …) — pass an explicit "
		"``is_group`` filter to include them."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def search_documents(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if _is_denied_doctype(doctype):
		return ToolResult.fail(
			f"search is not permitted on {doctype!r}",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	if not frappe.has_permission(doctype, "read", user=ctx.user):
		return ToolResult.fail(
			f"read permission denied on {doctype!r}",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	fields = _normalise_fields(args.get("fields"))
	filters = args.get("filters") or {}
	or_filters = args.get("or_filters") or None
	if not isinstance(filters, dict):
		filters = {}
	# Tree-doctype convention: hierarchical doctypes (Cost Center,
	# Account, Department, Warehouse, Item Group, …) carry an
	# ``is_group`` flag.  Group rows are containers, not transactional
	# records, so we default to ``is_group=0`` unless the caller has
	# explicitly opted into groups via the filter map.
	filters = _apply_is_group_default(doctype, filters)
	limit = _clamp_limit(args.get("limit"))
	order_by = (args.get("order_by") or "modified desc").strip() or "modified desc"

	publish_progress(
		ctx,
		tool_name="search_documents",
		user_visible_message=f"Searching {doctype}…",
		stage="search_start",
	)

	try:
		rows = frappe.get_list(
			doctype,
			filters=filters,
			or_filters=or_filters,
			fields=fields,
			limit_page_length=limit,
			order_by=order_by,
			user=ctx.user,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)
	except Exception as exc:
		return ToolResult.fail(
			str(exc) or exc.__class__.__name__,
			error_code="SEARCH_FAILED",
			stop_processing=False,
		)

	# Defensive row-level filter — frappe.get_list with user= already
	# honours read perms, but a separate has_permission pass per row
	# catches doctypes that rely on permission_query_conditions returning
	# a clause the caller might bypass via or_filters.
	visible: list[dict] = []
	for row in rows or []:
		name = row.get("name") if isinstance(row, dict) else None
		if not name:
			continue
		try:
			ok = frappe.has_permission(doctype, "read", doc=name, user=ctx.user)
		except Exception:
			ok = True
		if ok:
			visible.append(row)

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"rows": visible,
			"total_matched": len(visible),
			"limit": limit,
			"truncated": False,
		}
	)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_is_group_default(doctype: str, filters: dict) -> dict:
	"""Inject ``is_group=0`` when the target doctype is a tree doctype
	and the caller hasn't already pinned that filter.

	Tree detection uses meta — if the doctype's meta exposes an
	``is_group`` field we treat it as hierarchical.  Frappe / ERPNext
	conventions cover Cost Center, Account, Department, Warehouse,
	Item Group, Customer Group, Supplier Group, Territory, Project,
	BOM, etc.  Any caller wanting groups can pass
	``filters={"is_group": 1}`` (or ``["in", [0,1]]``) explicitly.
	"""
	if "is_group" in filters:
		return filters
	try:
		import frappe

		meta = frappe.get_meta(doctype)
	except Exception:
		return filters
	if not hasattr(meta, "get_field") or meta.get_field("is_group") is None:
		return filters
	new_filters = dict(filters)
	new_filters["is_group"] = 0
	return new_filters


def _is_denied_doctype(doctype: str) -> bool:
	if doctype in _DOCTYPE_DENY_LIST:
		return True
	return any(doctype.startswith(prefix) for prefix in _DENY_PREFIXES)


def _normalise_fields(value: Any) -> list[str]:
	if not isinstance(value, list) or not value:
		return ["name"]
	cleaned = [f for f in value if isinstance(f, str) and f.strip()]
	if not cleaned:
		return ["name"]
	if "name" not in cleaned:
		cleaned = ["name", *cleaned]
	# Cap projection breadth so a wide doctype can't blow the token
	# budget.  The registry-level cap trims further if needed.
	return cleaned[:_MAX_FIELDS]


def _clamp_limit(value: Any) -> int:
	try:
		limit = int(value) if value is not None else _DEFAULT_LIMIT
	except (TypeError, ValueError):
		limit = _DEFAULT_LIMIT
	return max(1, min(limit, _MAX_LIMIT))


__all__ = ["search_documents"]
