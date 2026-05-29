# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``delete_document`` — destructive deletion gated by ``confirm=true``.

The tool itself enforces four layers of safety:

1. The ``confirm`` argument must be ``true`` — the LLM cannot invoke a
   delete by accident (the schema requires the flag, and the handler
   refuses anything else).
2. ``System Manager`` role gate via ``requires_role`` plus the
   underlying ``frappe.has_permission(..., "delete")`` check.
3. Submitted submittable documents are refused — the caller must
   cancel them via the standard Frappe workflow first.
4. A pre-delete snapshot is captured in ``IDP Document Log`` so the
   record can be reconstructed within the reversibility window.  The
   audit row name doubles as the ``undo_token`` returned on success.
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_RATE_LIMIT_PER_HOUR = 5


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType."},
		"name": {"type": "string", "description": "Primary key of the record to delete."},
		"confirm": {
			"type": "boolean",
			"description": (
				"Must be true.  The agent sets this only after the user "
				"explicitly authorises the deletion through the UI dialog."
			),
		},
		"reason": {
			"type": "string",
			"description": "Optional free-text reason recorded on the audit row.",
		},
	},
	"required": ["doctype", "name", "confirm"],
	"additionalProperties": False,
}


@tool(
	name="delete_document",
	description=(
		"Delete an existing ERPNext record.  Destructive — only call this "
		"when the user has explicitly named the record they want deleted.  "
		"Refuses without confirm=true.  Cannot delete submitted submittable "
		"documents — cancel them first via the standard workflow.  Captures "
		"a snapshot in the audit log so the deletion is recoverable within "
		"the configured undo window via the returned undo_token."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	requires_role="System Manager",
	mutating=True,
)
def delete_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	confirm = bool(args.get("confirm"))
	reason = (args.get("reason") or "").strip() or None

	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not name:
		return ToolResult.fail(
			"name is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not confirm:
		return ToolResult.fail(
			"delete refused: confirm must be true",
			error_code="USER_CONFIRMATION_REQUIRED",
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

	try:
		from idp.core.rate_limit import check_and_consume_tool

		check_and_consume_tool(
			"delete_document",
			user=ctx.user,
			limit_per_hour=_RATE_LIMIT_PER_HOUR,
		)
	except Exception as exc:
		if exc.__class__.__name__ == "RateLimitExceededError":
			return ToolResult.fail(
				str(exc),
				error_code="RATE_LIMITED",
				stop_processing=True,
			)

	try:
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:  # type: ignore[attr-defined]
		return ToolResult.fail(
			f"{doctype} {name!r} not found",
			error_code="RECORD_NOT_FOUND",
			stop_processing=False,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	if not frappe.has_permission(doctype, "delete", doc=doc, user=ctx.user):
		return ToolResult.fail(
			f"delete permission denied on {doctype} {name!r}",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	docstatus = int(getattr(doc, "docstatus", 0) or 0)
	if docstatus == 1:
		return ToolResult.fail(
			(
				f"{doctype} {name!r} is submitted; cancel it via the standard "
				"workflow before deleting."
			),
			error_code="DOC_SUBMITTED",
			stop_processing=False,
		)

	# Snapshot prior to deletion so we can reconstruct the doc on undo.
	snapshot = _snapshot_doc(doc)

	publish_progress(
		ctx,
		tool_name="delete_document",
		user_visible_message=f"Deleting {doctype} {name}…",
		stage="delete_start",
	)

	try:
		doc.delete()
	except frappe.LinkExistsError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			(
				f"cannot delete {doctype} {name!r}: another document references it "
				f"({exc})."
			),
			error_code="LINK_EXISTS",
			stop_processing=False,
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
			error_code="DELETE_FAILED",
			stop_processing=True,
		)

	undo_token: str | None = None
	try:
		from idp.core.audit import log_doc_delete

		undo_token = log_doc_delete(
			doctype=doctype,
			name=name,
			snapshot=snapshot,
			user=ctx.user,
			reason=reason,
			company=ctx.company,
			success=True,
		)
	except Exception:
		pass

	body = f"{doctype} {name} was deleted."
	return ToolResult(
		success=True,
		data={
			"doctype": doctype,
			"name": name,
			"deleted": True,
			"undo_token": undo_token,
		},
		card={
			"card_type": "InfoCard",
			"title": f"{doctype} deleted",
			"body": body,
			"undo_token": undo_token,
		},
		stop_processing=True,
	)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot_doc(doc: Any) -> dict:
	"""Capture the doc as a plain dict suitable for re-insertion on undo."""
	try:
		data = doc.as_dict()
	except Exception:
		return {}
	# Strip framework bookkeeping fields the recreate path can't accept.
	for key in (
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
		"_seen",
		"docstatus",
	):
		data.pop(key, None)
	return data


__all__ = ["delete_document"]
