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

from idp.llm.tools.base import ToolContext, ToolResult, publish_progress, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "Target ERPNext DocType."},
		"header": {"type": "object", "additionalProperties": True},
		"items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
		"taxes": {
			"type": "array",
			"description": "Tax rows from the proposed mapping (each carries an Account-name in 'account_head' or 'account').",
			"items": {"type": "object", "additionalProperties": True},
		},
		"child_tables": {
			"type": "object",
			"description": (
				"Optional generic bag of child rows keyed by parent fieldname "
				"(e.g. 'payment_schedule'). Use when checking child tables "
				"other than items/taxes."
			),
			"additionalProperties": {
				"type": "array",
				"items": {"type": "object", "additionalProperties": True},
			},
		},
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
	taxes = args.get("taxes") or []
	extra_child_tables = args.get("child_tables") or {}
	if not isinstance(header, dict):
		header = {}
	if not isinstance(items, list):
		items = []
	if not isinstance(taxes, list):
		taxes = []
	if not isinstance(extra_child_tables, dict):
		extra_child_tables = {}

	publish_progress(
		ctx,
		tool_name="list_missing_masters",
		user_visible_message=f"Checking {doctype} masters (suppliers / items / accounts)…",
		stage="lookup_start",
	)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	from idp.mappers.base import get_doctype_schema

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
	# ``child_tables`` is a dict keyed by parent fieldname (e.g. "items"):
	#   {"items": {"doctype": "Purchase Invoice Item", "fields": [...]}, ...}
	# Be defensive and accept the (legacy) list-of-dicts shape too.
	raw_child_tables = schema.get("child_tables") or {}
	child_links: dict[str, dict[str, str]] = {}
	if isinstance(raw_child_tables, dict):
		for parent_field, ct in raw_child_tables.items():
			if isinstance(ct, dict):
				child_links[parent_field] = _link_fields(ct.get("fields") or [])
	elif isinstance(raw_child_tables, list):
		for ct in raw_child_tables:
			if isinstance(ct, dict) and ct.get("fieldname"):
				child_links[ct["fieldname"]] = _link_fields(ct.get("fields") or [])

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

	# ------------------------------------------------------------------
	# Walk every supplied child table against its schema-declared Link
	# fields.  We accept the legacy ``items`` + roadmap-§30 ``taxes``
	# arguments plus a generic ``child_tables`` bag for forward
	# compatibility.  Roadmap §30 fix: previously only ``items`` was
	# iterated, so unmapped tax accounts and unmapped non-item child
	# rows were silently missed.
	# ------------------------------------------------------------------
	tables_to_check: dict[str, list] = {}
	if items:
		tables_to_check["items"] = items
	if taxes:
		tables_to_check["taxes"] = taxes
	for parent_field, rows in extra_child_tables.items():
		if isinstance(rows, list) and rows:
			tables_to_check[parent_field] = rows

	def _check_row_against(link_map: dict[str, str], row: dict) -> None:
		for fieldname, link_doctype in link_map.items():
			# Direct Link fieldname (e.g. ``item_code``, ``account_head``).
			if fieldname in row:
				_check(fieldname, link_doctype, row.get(fieldname))
				continue
			# LLM-supplied rows often carry the extracted *label* under a
			# loose key like ``name``, ``description``, or ``account``.
			# Map those to the corresponding Link doctype so we still
			# detect e.g. "IGST" as a missing Account when the LLM
			# hasn't populated ``account_head`` yet.
			fallback_keys = _FALLBACK_KEYS_BY_LINK_DOCTYPE.get(link_doctype, ())
			for k in fallback_keys:
				val = row.get(k)
				if isinstance(val, str) and val.strip():
					_check(fieldname, link_doctype, val)
					break

	for parent_field, rows in tables_to_check.items():
		# Prefer the schema-declared link map for this parent fieldname;
		# fall back to *any* child table if the LLM used a non-standard
		# parent name.
		link_map = child_links.get(parent_field) or {}
		if not link_map:
			# Try every child-table — useful when the LLM passes
			# ``taxes`` but the schema names it ``purchase_taxes_and_charges``.
			merged: dict[str, str] = {}
			for cm in child_links.values():
				merged.update(cm)
			link_map = merged
		for row in rows:
			if not isinstance(row, dict):
				continue
			_check_row_against(link_map, row)

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"missing": missing,
			"count": len(missing),
		}
	)


# Loose-key fallbacks keyed by the *target* Link doctype.  When the LLM
# supplies an item/tax row without populating the canonical Link
# fieldname, we still want to flag the extracted label so the user gets
# a missing-master warning instead of a silent pass.
_FALLBACK_KEYS_BY_LINK_DOCTYPE: dict[str, tuple[str, ...]] = {
	"Item": ("item_code", "item_name", "name", "description", "code"),
	"Account": ("account_head", "account", "name"),
	"Supplier": ("supplier", "supplier_name", "name"),
	"Customer": ("customer", "customer_name", "name"),
	"UOM": ("uom", "name"),
}


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
