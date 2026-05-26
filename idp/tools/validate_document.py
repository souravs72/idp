# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``validate_document`` — run rule-based business validators on a mapping.

Wraps :func:`idp.validators.business_rules.validate_business_rules`
in the standard tool envelope.  Validation failures are *retryable*
(``stop_processing=False``) so the LLM can fix and call the tool
again with corrected fields.
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "Target ERPNext DocType name."},
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
		"company": {
			"type": "string",
			"description": "Company context (defaults to conversation company).",
		},
	},
	"required": ["doctype", "header"],
	"additionalProperties": False,
}


@tool(
	name="validate_document",
	description=(
		"Run rule-based business validators (date ordering, totals, currency, "
		"line-item math, fiscal year) on a proposed mapping.  Returns a list of "
		"warnings; an empty list means the mapping passed.  Validation failures "
		"are retryable — fix the fields and call again."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def validate_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or ctx.target_doctype or "").strip()
	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	header = args.get("header") or {}
	if not isinstance(header, dict):
		return ToolResult.fail(
			"header must be an object",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	items = args.get("items") or []
	if not isinstance(items, list):
		items = []

	company = (args.get("company") or ctx.company or "") or ""

	publish_progress(
		ctx,
		tool_name="validate_document",
		user_visible_message=f"Validating {doctype} against business rules…",
		stage="validate_start",
	)

	# Local imports keep cold-start cost low.
	from idp.mappers.base import MappedDocument
	from idp.validators.business_rules import validate_business_rules

	mapped = MappedDocument(doctype=doctype, header=header, items=items)
	warnings = validate_business_rules(mapped, company=company)

	return ToolResult.ok(
		data={
			"doctype": doctype,
			"warnings": warnings,
			"is_valid": len(warnings) == 0,
		}
	)


__all__ = ["validate_document"]
