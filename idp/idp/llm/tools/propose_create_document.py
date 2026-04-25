# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``propose_create_document`` — render a ConfirmationCard for the user.

This is **non-mutating**: it does not insert the ERPNext doc.  Instead
it builds the card payload (extracted fields, prerequisites, action
buttons) that the chatbot UI will render so the user can review,
edit, and confirm before ``create_document`` is called.

The card payload follows the schema documented in roadmap §20.  Phase
19 only needs the envelope; Phase 20 layers the rich validation on
top.
"""

from __future__ import annotations

from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "Target ERPNext DocType."},
		"header": {
			"type": "object",
			"description": "Field name → value map for the parent doc.",
			"additionalProperties": True,
		},
		"items": {
			"type": "array",
			"description": "Optional child-table rows.",
			"items": {"type": "object", "additionalProperties": True},
		},
		"file_id": {
			"type": "string",
			"description": "Source attachment alias (file_1, file_2, ...) for provenance.",
		},
		"confidence_scores": {
			"type": "object",
			"description": "Per-field confidence scores from the mapper.",
			"additionalProperties": True,
		},
		"warnings": {
			"type": "array",
			"description": "Validator warnings to surface alongside the fields.",
			"items": {"type": "string"},
		},
		"missing_masters": {
			"type": "array",
			"description": "List of {link_doctype, name} that need creation first.",
			"items": {"type": "object", "additionalProperties": True},
		},
		"summary": {
			"type": "string",
			"description": "Short user-facing summary of what is about to be created.",
		},
	},
	"required": ["doctype", "header"],
	"additionalProperties": False,
}


@tool(
	name="propose_create_document",
	description=(
		"Render a ConfirmationCard to the user with the extracted fields, "
		"warnings, and missing prerequisites.  This does NOT create the "
		"ERPNext document — the user must explicitly confirm in the UI before "
		"create_document is called.  Always call this before create_document."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def propose_create_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	header = args.get("header") or {}
	if not isinstance(header, dict) or not header:
		return ToolResult.fail(
			"header object with at least one field is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	card_payload = {
		"card_type": "ConfirmationCard",
		"doctype": doctype,
		"header": header,
		"items": args.get("items") or [],
		"file_id": args.get("file_id"),
		"confidence_scores": args.get("confidence_scores") or {},
		"warnings": args.get("warnings") or [],
		"missing_masters": args.get("missing_masters") or [],
		"summary": args.get("summary") or f"Review the proposed {doctype} below.",
		"actions": [
			{"id": "save_draft", "label": "Save as Draft"},
			{"id": "submit", "label": "Submit"},
			{"id": "cancel", "label": "Cancel"},
		],
		"company": ctx.company,
	}

	return ToolResult.ok(
		data={
			"awaiting_user_confirmation": True,
			"doctype": doctype,
		},
		card=card_payload,
	)


__all__ = ["propose_create_document"]
