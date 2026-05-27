# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``resolve_masters`` — inspect or create missing master records.

Consolidates the former ``list_missing_masters`` (mode="report") and
``create_master`` (mode="create") into a single tool, halving the LLM
schema surface for these closely-related read/write operations on the
same master data set.

mode="report"  — walk the proposed mapping and return any referenced
                master records that don't exist yet.
mode="create"  — create a single missing master record after the user
                has approved via the ConfirmationCard (user_confirmed=true).
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

# {doctype: required_fieldnames} — same whitelist as former create_master
_ALLOWED_MASTERS: dict[str, list[str]] = {
	"Supplier": ["supplier_name"],
	"Customer": ["customer_name"],
	"Item": ["item_code", "item_name", "item_group"],
	"UOM": ["uom_name"],
	"Account": ["account_name", "account_type"],
	"Item Group": ["item_group_name"],
	"Supplier Group": ["supplier_group_name"],
	"Customer Group": ["customer_group_name"],
}

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"mode": {
			"type": "string",
			"enum": ["report", "create"],
			"description": (
				'"report": inspect a proposed mapping and return every referenced master '
				"that does not exist yet. "
				'"create": create one missing master record after user approval '
				"(requires user_confirmed=true)."
			),
		},
		"doctype": {
			"type": "string",
			"description": (
				"Target ERPNext DocType (report mode) or master DocType to create (create mode)."
			),
		},
		# --- report mode ---
		"header": {
			"type": "object",
			"additionalProperties": True,
			"description": "Header field map (report mode).",
		},
		"items": {
			"type": "array",
			"items": {"type": "object", "additionalProperties": True},
			"description": "Item rows (report mode).",
		},
		"taxes": {
			"type": "array",
			"description": "Tax rows; each carries an Account name in 'account_head' or 'account' (report mode).",
			"items": {"type": "object", "additionalProperties": True},
		},
		"child_tables": {
			"type": "object",
			"description": "Generic bag of child rows keyed by parent fieldname (report mode).",
			"additionalProperties": {
				"type": "array",
				"items": {"type": "object", "additionalProperties": True},
			},
		},
		# --- create mode ---
		"fields": {
			"type": "object",
			"description": "Field map for the new master record (create mode only).",
			"additionalProperties": True,
		},
		"user_confirmed": {
			"type": "boolean",
			"description": (
				"create mode only. Must be true. The agent injects this only when the user "
				"has explicitly approved master creation via the ConfirmationCard. "
				"The LLM must NOT set this autonomously."
			),
		},
	},
	"required": ["mode", "doctype"],
	"additionalProperties": False,
}


@tool(
	name="resolve_masters",
	description=(
		"Inspect or create missing master records. "
		'mode="report": walk a proposed mapping and return masters (Supplier, Customer, '
		"Item, UOM, Account, ...) that don't exist yet — call before propose_create_document. "
		'mode="create": create one missing master after user approval (set user_confirmed=true '
		"only when the user has approved via ConfirmationCard — NEVER set it autonomously)."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	mutating=True,
)
def resolve_masters(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	mode = (args.get("mode") or "").strip()
	if mode not in ("report", "create"):
		return ToolResult.fail(
			"mode must be 'report' or 'create'",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if mode == "report":
		return _report(args, ctx)
	return _create(args, ctx)


# ---------------------------------------------------------------------------
# report mode (formerly list_missing_masters)
# ---------------------------------------------------------------------------


def _report(args: dict, ctx: ToolContext) -> ToolResult:
	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail("doctype is required", error_code="MISSING_ARGUMENT", stop_processing=False)

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
		tool_name="resolve_masters",
		user_visible_message=f"Checking {doctype} masters (suppliers / items / accounts)…",
		stage="lookup_start",
	)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail("frappe runtime not available", error_code="UNEXPECTED_ERROR", stop_processing=True)

	from idp.mappers.base import get_doctype_schema

	try:
		schema = get_doctype_schema(doctype)
	except Exception as exc:
		return ToolResult.fail(
			f"failed to load schema for {doctype}: {exc}",
			error_code="IDP_ERROR",
			stop_processing=False,
		)

	header_links = _link_fields(schema.get("fields") or [])
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
			missing.append({"fieldname": fieldname, "link_doctype": link_doctype, "name": value})

	for fieldname, link_doctype in header_links.items():
		_check(fieldname, link_doctype, header.get(fieldname))

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
			if fieldname in row:
				_check(fieldname, link_doctype, row.get(fieldname))
				continue
			fallback_keys = _FALLBACK_KEYS_BY_LINK_DOCTYPE.get(link_doctype, ())
			for k in fallback_keys:
				val = row.get(k)
				if isinstance(val, str) and val.strip():
					_check(fieldname, link_doctype, val)
					break

	for parent_field, rows in tables_to_check.items():
		link_map = child_links.get(parent_field) or {}
		if not link_map:
			merged: dict[str, str] = {}
			for cm in child_links.values():
				merged.update(cm)
			link_map = merged
		for row in rows:
			if not isinstance(row, dict):
				continue
			_check_row_against(link_map, row)

	return ToolResult.ok(data={"doctype": doctype, "missing": missing, "count": len(missing)})


# ---------------------------------------------------------------------------
# create mode (formerly create_master)
# ---------------------------------------------------------------------------


def _create(args: dict, ctx: ToolContext) -> ToolResult:
	if not args.get("user_confirmed"):
		return ToolResult.fail(
			"user has not confirmed master creation — call "
			"propose_create_document and let the user approve missing_masters "
			"via the ConfirmationCard first",
			error_code="USER_CONFIRMATION_REQUIRED",
			stop_processing=True,
		)

	doctype = (args.get("doctype") or "").strip()
	fields = args.get("fields") or {}

	if doctype not in _ALLOWED_MASTERS:
		return ToolResult.fail(
			f"creating {doctype!r} via this tool is not permitted",
			error_code="MASTER_NOT_ALLOWED",
			stop_processing=True,
		)
	if not isinstance(fields, dict) or not fields:
		return ToolResult.fail("fields object is required", error_code="MISSING_ARGUMENT", stop_processing=False)

	required = _ALLOWED_MASTERS[doctype]
	missing_fields = [r for r in required if not fields.get(r)]
	if missing_fields:
		return ToolResult.fail(
			f"missing required fields for {doctype}: {', '.join(missing_fields)}",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail("frappe runtime not available", error_code="UNEXPECTED_ERROR", stop_processing=True)

	probe_label = fields.get(required[0]) or fields.get("name") or doctype
	publish_progress(
		ctx,
		tool_name="resolve_masters",
		user_visible_message=f"Creating {doctype} {probe_label!r}…",
		stage="create_master_start",
	)

	probe_name = _probe_existing_name(doctype, fields)
	if probe_name and frappe.db.exists(doctype, probe_name):
		return ToolResult.ok(
			data={
				"doctype": doctype,
				"name": probe_name,
				"existed": True,
				"message": f"{doctype} {probe_name!r} already exists; reused.",
			}
		)

	try:
		doc = frappe.new_doc(doctype)
		for k, v in fields.items():
			doc.set(k, v)
		doc.insert()
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(str(exc) or "permission denied", error_code="PERMISSION_DENIED", stop_processing=True)
	except Exception as exc:
		exc_name = exc.__class__.__name__
		exc_msg = str(exc) or exc_name
		looks_like_duplicate = (
			isinstance(exc, getattr(frappe, "DuplicateEntryError", ()))
			or exc_name in {"DuplicateEntryError", "IntegrityError", "UniqueValidationError"}
			or "Duplicate entry" in exc_msg
			or "already exists" in exc_msg.lower()
		)
		if looks_like_duplicate:
			retry_name = probe_name or fields.get(required[0])
			if retry_name and frappe.db.exists(doctype, retry_name):
				return ToolResult.ok(
					data={
						"doctype": doctype,
						"name": retry_name,
						"existed": True,
						"message": f"{doctype} {retry_name!r} already exists; reused.",
					}
				)
			return ToolResult.fail(exc_msg, error_code="DUPLICATE_MASTER", stop_processing=False)
		return ToolResult.fail(exc_msg, error_code="INSERT_FAILED", stop_processing=False)

	return ToolResult.ok(data={"doctype": doctype, "name": doc.name, "existed": False})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _probe_existing_name(doctype: str, fields: dict) -> str | None:
	primary_field_by_doctype = {
		"Supplier": "supplier_name",
		"Customer": "customer_name",
		"Item": "item_code",
		"UOM": "uom_name",
		"Account": "account_name",
		"Item Group": "item_group_name",
		"Supplier Group": "supplier_group_name",
		"Customer Group": "customer_group_name",
	}
	field = primary_field_by_doctype.get(doctype)
	if not field:
		return None
	value = fields.get(field)
	if isinstance(value, str) and value.strip():
		return value.strip()
	return None


__all__ = ["resolve_masters"]
