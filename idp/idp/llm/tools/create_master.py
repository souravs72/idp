# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``create_master`` — create a missing master record (Supplier/Customer/Item/...).

Allowed master DocTypes are explicitly whitelisted to avoid the LLM
asking the agent to create unrelated documents.  Each whitelist entry
declares the minimum required fields the LLM must supply.
"""

from __future__ import annotations

from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

# {doctype: required_fieldnames}
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
		"doctype": {
			"type": "string",
			"enum": list(_ALLOWED_MASTERS.keys()),
			"description": "Master DocType to create.",
		},
		"fields": {
			"type": "object",
			"description": "Field map for the master record.  Must include the required fields.",
			"additionalProperties": True,
		},
	},
	"required": ["doctype", "fields"],
	"additionalProperties": False,
}


@tool(
	name="create_master",
	description=(
		"Create a missing master record (Supplier, Customer, Item, UOM, Account, "
		"...).  Use after list_missing_masters reports gaps.  Only the "
		"whitelisted master DocTypes are accepted."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	mutating=True,
)
def create_master(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	fields = args.get("fields") or {}

	if doctype not in _ALLOWED_MASTERS:
		return ToolResult.fail(
			f"creating {doctype!r} via this tool is not permitted",
			error_code="MASTER_NOT_ALLOWED",
			stop_processing=True,
		)
	if not isinstance(fields, dict) or not fields:
		return ToolResult.fail(
			"fields object is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	required = _ALLOWED_MASTERS[doctype]
	missing = [r for r in required if not fields.get(r)]
	if missing:
		return ToolResult.fail(
			f"missing required fields for {doctype}: {', '.join(missing)}",
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
		doc = frappe.new_doc(doctype)
		for k, v in fields.items():
			doc.set(k, v)
		doc.insert()
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)
	except Exception as exc:
		return ToolResult.fail(
			str(exc) or exc.__class__.__name__,
			error_code="INSERT_FAILED",
			stop_processing=True,
		)

	return ToolResult.ok(
		data={"doctype": doctype, "name": doc.name},
	)


__all__ = ["create_master"]
