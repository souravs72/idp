# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``create_document`` — actually insert (and optionally submit) an ERPNext doc.

This is **mutating**.  The roadmap (§19.6 rule 2 and §20) requires
that the LLM has already presented the data to the user via
``propose_create_document`` and that the user confirmed in the UI.
Confirmation is signalled by the API endpoint that invokes this tool
with ``user_confirmed=True`` (the LLM cannot fabricate this — the
agent rejects unconfirmed mutating calls).

Failure modes are stop-on-error: a DB-level insert failure means the
agent loop must halt rather than letting the LLM retry with subtly
different fields.
"""

from __future__ import annotations

from idp.llm.tools.base import ToolContext, ToolResult, publish_progress, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType to insert."},
		"header": {
			"type": "object",
			"description": "Field name → value map for the parent doc.",
			"additionalProperties": True,
		},
		"items": {
			"type": "array",
			"description": "Child-table rows (will be appended to the canonical child fieldname).",
			"items": {"type": "object", "additionalProperties": True},
		},
		"items_fieldname": {
			"type": "string",
			"description": "Child-table fieldname — defaults to 'items' (most transaction docs).",
		},
		"submit": {
			"type": "boolean",
			"description": "If True, also call submit() after insert.  Default false (draft).",
		},
		"user_confirmed": {
			"type": "boolean",
			"description": (
				"Must be true.  The agent injects this only when the user has "
				"confirmed via the ConfirmationCard."
			),
		},
	},
	"required": ["doctype", "header", "user_confirmed"],
	"additionalProperties": False,
}


@tool(
	name="create_document",
	description=(
		"Create an ERPNext document from a confirmed mapping.  Only call this "
		"after the user confirms the ConfirmationCard rendered by "
		"propose_create_document.  Failures are stop-on-error — never retry "
		"silently."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	mutating=True,
)
def create_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}

	if not args.get("user_confirmed"):
		return ToolResult.fail(
			"user has not confirmed the ConfirmationCard — call "
			"propose_create_document and wait for explicit user confirmation first",
			error_code="USER_CONFIRMATION_REQUIRED",
			stop_processing=True,
		)

	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=True,
		)
	header = args.get("header") or {}
	if not isinstance(header, dict) or not header:
		return ToolResult.fail(
			"header object with at least one field is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=True,
		)
	items = args.get("items") or []
	if not isinstance(items, list):
		items = []
	items_fieldname = (args.get("items_fieldname") or "items").strip() or "items"
	should_submit = bool(args.get("submit"))

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	publish_progress(
		ctx,
		tool_name="create_document",
		user_visible_message=(
			f"Submitting {doctype} to ERPNext…"
			if should_submit
			else f"Saving {doctype} as draft…"
		),
		stage="insert_start",
	)

	# Build the doc — use frappe.new_doc so default values are applied.
	try:
		doc = frappe.new_doc(doctype)
		for key, value in header.items():
			doc.set(key, value)
		if items:
			for row in items:
				if isinstance(row, dict):
					doc.append(items_fieldname, row)
		doc.insert()
		if should_submit:
			doc.submit()
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

	# Terminal turn: the InfoCard payload already carries the
	# user-facing confirmation text and a deep-link to the new record.
	# Stop the agent loop here so we don't pay for an extra LLM call
	# that would only re-render the same "X created" sentence.
	body = (
		f"{doctype} {doc.name} was submitted."
		if should_submit
		else f"{doctype} {doc.name} was saved as draft."
	)
	return ToolResult(
		success=True,
		data={
			"doctype": doctype,
			"name": doc.name,
			"docstatus": getattr(doc, "docstatus", 0),
			"submitted": should_submit,
		},
		card={
			"card_type": "InfoCard",
			"title": f"{doctype} created",
			"body": body,
			"link": {"doctype": doctype, "name": doc.name},
		},
		stop_processing=True,
	)


__all__ = ["create_document"]
