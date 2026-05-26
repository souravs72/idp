# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``create_master`` — create a missing master record (Supplier/Customer/Item/...).

Allowed master DocTypes are explicitly whitelisted to avoid the LLM
asking the agent to create unrelated documents.  Each whitelist entry
declares the minimum required fields the LLM must supply.
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

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
		"user_confirmed": {
			"type": "boolean",
			"description": (
				"Must be true.  The agent injects this only when the user has "
				"explicitly approved master creation via the ConfirmationCard "
				"(missing_masters review).  The LLM must NOT set this on its "
				"own — surface gaps via propose_create_document instead."
			),
		},
	},
	"required": ["doctype", "fields", "user_confirmed"],
	"additionalProperties": False,
}


@tool(
	name="create_master",
	description=(
		"Create a missing master record (Supplier, Customer, Item, UOM, Account, "
		"...).  REQUIRES user_confirmed=True, which only the agent can set after "
		"the user approves master creation in the ConfirmationCard.  Do NOT call "
		"this autonomously — surface missing masters via propose_create_document."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	mutating=True,
)
def create_master(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}

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

	# Best-effort label for the progress banner: prefer the primary
	# identifier field, fall back to whatever the user supplied.
	probe_label = (
		fields.get(required[0])
		or fields.get("name")
		or doctype
	)
	publish_progress(
		ctx,
		tool_name="create_master",
		user_visible_message=f"Creating {doctype} {probe_label!r}…",
		stage="create_master_start",
	)

	# ---- Idempotency: if a matching record already exists, reuse it ---------
	# Most masters use the user-supplied identifier as the primary key
	# (e.g. Supplier.supplier_name autoname=field, Item.item_code).  The
	# LLM occasionally double-calls create_master in the same turn — on
	# the second call we want to return success, not a duplicate-key
	# error that stops the whole agent loop.
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
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)
	except Exception as exc:
		# Duplicate-entry race: another path (or the LLM's previous call
		# in the same turn) inserted the same master between our probe
		# and the insert.  Treat as success and let the agent continue.
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
						"message": (
							f"{doctype} {retry_name!r} already exists; reused."
						),
					}
				)
			# Couldn't resolve the existing name — surface a non-stopping error
			# so the LLM can rethink (e.g. call list_missing_masters again).
			return ToolResult.fail(
				exc_msg,
				error_code="DUPLICATE_MASTER",
				stop_processing=False,
			)
		return ToolResult.fail(
			exc_msg,
			error_code="INSERT_FAILED",
			stop_processing=False,
		)

	return ToolResult.ok(
		data={"doctype": doctype, "name": doc.name, "existed": False},
	)


def _probe_existing_name(doctype: str, fields: dict) -> str | None:
	"""Best-effort: figure out what name the master *would* take on insert,
	so we can short-circuit when it already exists.

	Each whitelisted master has a stable identifier field; this maps
	doctype → the field whose value Frappe will use as ``name`` (or
	close enough for an existence probe).
	"""

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


__all__ = ["create_master"]
