# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``list_missing_masters`` — report referenced masters that don't exist yet.

Walks the proposed mapping (header + items), inspects every Link
field in the target DocType's schema, and returns the list of
referenced names that are absent from the corresponding master.

This is the precursor to ``create_master``: the LLM iterates the
returned list, asks the user (or the data) for any extra fields, and
calls ``create_master`` once per missing entry before retrying
``propose_create_document``.
"""

from __future__ import annotations

from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "Target ERPNext DocType."},
		"header": {"type": "object", "additionalProperties": True},
		"items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
	},
	"required": ["doctype", "header"],
	"additionalProperties": False,
}


@tool(
	name="list_missing_masters",
	description=(
		"Inspect a proposed mapping and return any referenced master records "
		"(Supplier, Customer, Item, UOM, Account, ...) that don't exist yet.  "
		"Call create_master for each entry before re-trying "
		"propose_create_document."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def list_missing_masters(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	header = args.get("header") or {}
	items = args.get("items") or []
	if not isinstance(header, dict):
		header = {}
	if not isinstance(items, list):
		items = []

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	from idp.idp.mappers.base import get_doctype_schema

	# Build {fieldname: link_doctype} for header and child tables.
	try:
		schema = get_doctype_schema(doctype)
	except Exception as exc:
		return ToolResult.fail(
			f"failed to load schema for {doctype}: {exc}",
			error_code="IDP_ERROR",
			stop_processing=False,
		)

	header_links = _link_fields(schema.get("fields") or [])
	child_links: dict[str, dict[str, str]] = {
		ct["fieldname"]: _link_fields(ct.get("fields") or []) for ct in (schema.get("child_tables") or [])
	}

	missing: list[dict] = []
	seen: set[tuple[str, str]] = set()

	def _check(fieldname: str, link_doctype: str, value: object) -> None:
		if not value or not isinstance(value, str):
			return
		key = (link_doctype, value)
		if key in seen:
			return
		seen.add(key)
		try:
			exists = frappe.db.exists(link_doctype, value)
		except Exception:
			exists = None
		if not exists:
			missing.append(
				{
					"fieldname": fieldname,
					"link_doctype": link_doctype,
					"name": value,
				}
			)

	for fieldname, link_doctype in header_links.items():
		_check(fieldname, link_doctype, header.get(fieldname))

	# Items child rows — schema lookup uses the *parent* fieldname (e.g. "items").
	for row in items:
		if not isinstance(row, dict):
			continue
		# Find which child-table this row most likely belongs to: prefer the
		# one whose link fields appear in the row.
		for _ct_field, link_map in child_links.items():
			for fieldname, link_doctype in link_map.items():
				if fieldname in row:
					_check(fieldname, link_doctype, row.get(fieldname))

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"missing": missing,
			"count": len(missing),
		}
	)


def _link_fields(field_defs: list[dict]) -> dict[str, str]:
	out: dict[str, str] = {}
	for f in field_defs:
		if (f.get("fieldtype") or "") == "Link":
			fn = f.get("fieldname")
			lt = f.get("options")
			if fn and lt:
				out[fn] = lt
	return out


__all__ = ["list_missing_masters"]
