# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""HTTP API for the IDP Conversation / Message DocTypes.

Exposes CRUD and list endpoints consumed by the chatbot frontend (Phase
19+).  The heavy LLM orchestration lives elsewhere; this module only
handles persistence and retrieval.

All endpoints are guarded by Frappe's permission system and the
``has_conversation_permission`` hook registered in ``hooks.py``.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from idp.core.config import get_default_company
from idp.core.logger import get_logger

logger = get_logger("idp.api.conversation")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_login() -> str:
	"""Return the current session user, rejecting guests."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)
	return user


def _load_conversation(conversation_id: str) -> "frappe.Document":
	"""Load an IDP Conversation enforcing read permission."""
	doc = frappe.get_doc("IDP Conversation", conversation_id)
	# `has_permission` is wired in hooks.py and uses the owner check.
	if not frappe.has_permission("IDP Conversation", ptype="read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return doc


def _parse_json_arg(value, default):
	"""Best-effort JSON parse: accept dict/list or str."""
	if value is None or value == "":
		return default
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return default


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_conversation(
	title: str | None = None,
	target_doctype: str | None = None,
	company: str | None = None,
	llm_provider: str | None = None,
	llm_model: str | None = None,
	ocr_language: str | None = None,
	output_language: str | None = None,
) -> dict:
	"""Create a new IDP Conversation owned by the session user.

	Returns ``{conversation_id, title, status}``.
	"""
	user = _require_login()

	doc = frappe.new_doc("IDP Conversation")
	doc.user = user
	doc.title = title or ""
	doc.target_doctype = target_doctype
	doc.company = company
	doc.llm_provider = llm_provider
	doc.llm_model = llm_model
	doc.ocr_language = ocr_language
	doc.output_language = output_language or "English"
	doc.status = "Active"
	doc.insert(ignore_permissions=False)

	logger.info("Created IDP Conversation %s for user=%s", doc.name, user)

	return {
		"conversation_id": doc.name,
		"title": doc.title,
		"status": doc.status,
	}


@frappe.whitelist()
def list_conversations(status: str = "Active", limit: int = 50) -> list[dict]:
	"""Return the caller's conversations, newest first.

	System Managers / Administrator see all conversations.  Ordinary
	users only see their own rows (enforced by
	``get_permission_query_conditions``).
	"""
	_require_login()
	limit = max(1, min(int(limit or 50), 500))

	filters: dict = {}
	if status:
		filters["status"] = status

	rows = frappe.get_list(
		"IDP Conversation",
		filters=filters,
		fields=[
			"name",
			"title",
			"user",
			"status",
			"target_doctype",
			"company",
			"llm_provider",
			"llm_model",
			"message_count",
			"total_tokens_used",
			"estimated_cost_usd",
			"last_message_on",
			"modified",
			"creation",
		],
		order_by="modified desc",
		limit_page_length=limit,
	)
	return rows


@frappe.whitelist()
def get_conversation(conversation_id: str) -> dict:
	"""Return conversation + ordered messages + attachments."""
	_require_login()
	doc = _load_conversation(conversation_id)

	messages = frappe.get_all(
		"IDP Message",
		filters={"conversation": doc.name},
		fields=[
			"name",
			"sequence",
			"role",
			"content",
			"tool_call_id",
			"tool_name",
			"tool_arguments",
			"tool_result",
			"attachments",
			"stop_processing",
			"rendered_card_type",
			"rendered_card_payload",
			"tokens_in",
			"tokens_out",
			"latency_ms",
			"created_on",
			"error",
		],
		order_by="sequence asc",
		limit_page_length=10000,
	)

	attachments = [
		{
			"file_id": row.file_id,
			"file_name": row.file_name,
			"file_url": row.file_url,
			"mime_type": row.mime_type,
			"file_size": row.file_size,
			"uploaded_on": row.uploaded_on,
		}
		for row in (doc.attachments or [])
	]

	return {
		"conversation_id": doc.name,
		"title": doc.title,
		"user": doc.user,
		"status": doc.status,
		"target_doctype": doc.target_doctype,
		"company": doc.company,
		"llm_provider": doc.llm_provider,
		"llm_model": doc.llm_model,
		"ocr_language": doc.ocr_language,
		"output_language": doc.output_language,
		"total_tokens_used": doc.total_tokens_used or 0,
		"estimated_cost_usd": doc.estimated_cost_usd or 0,
		"message_count": doc.message_count or 0,
		"last_message_on": doc.last_message_on,
		"creation": doc.creation,
		"modified": doc.modified,
		"metadata": _parse_json_arg(doc.metadata, {}),
		"attachments": attachments,
		"messages": messages,
	}


@frappe.whitelist()
def post_message(
	conversation_id: str,
	content: str = "",
	attachments: str = "[]",
	role: str = "user",
) -> dict:
	"""Append a message to a conversation.

	Persists the row and returns the created message metadata.  The
	caller (or a downstream assistant loop) is responsible for invoking
	the LLM — this endpoint only handles persistence.
	"""
	_require_login()
	doc = _load_conversation(conversation_id)

	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	parsed_attachments = _parse_json_arg(attachments, [])
	if not isinstance(parsed_attachments, list):
		frappe.throw(_("attachments must be a JSON array"))

	message = frappe.new_doc("IDP Message")
	message.conversation = doc.name
	message.role = role or "user"
	message.content = content or ""
	message.attachments = json.dumps(parsed_attachments) if parsed_attachments else None
	message.created_on = frappe.utils.now_datetime()
	message.insert(ignore_permissions=False)

	# Auto-generate title on first user message if not set
	if (not doc.title or doc.title.startswith("Conversation —")) and role == "user" and content:
		preview = content.strip().splitlines()[0][:120]
		if preview:
			doc.title = preview
			doc.db_update()

	return {
		"message_id": message.name,
		"conversation_id": doc.name,
		"sequence": message.sequence,
		"role": message.role,
		"created_on": message.created_on,
	}


@frappe.whitelist()
def archive_conversation(conversation_id: str) -> dict:
	"""Set status=Archived.  Preserves the full transcript for audit."""
	_require_login()
	doc = _load_conversation(conversation_id)

	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	doc.status = "Archived"
	doc.save(ignore_permissions=False)

	logger.info("Archived IDP Conversation %s", doc.name)
	return {"conversation_id": doc.name, "status": doc.status}


@frappe.whitelist()
def run_agent(
	conversation_id: str,
	content: str = "",
	attachments: str = "[]",
	user_confirmed_action: str | None = None,
) -> dict:
	"""Append the user's message and run one round of the IDP agent loop.

	This is the Phase 19 entry point that wires the LLM tool-calling
	runtime into the chatbot UX.  Realtime events are published while
	the loop runs (see :class:`IDPAgent`); this call returns once the
	loop terminates with a structured summary of the new messages and
	the stop reason.

	*user_confirmed_action* (optional JSON object) is set by the
	frontend when the user clicks Submit on a ConfirmationCard — it
	signals to the agent that the next ``create_document`` call
	carrying matching ``user_confirmed=True`` is authorised.

	Errors raised by the agent (LLM unavailable, OCR failed, missing
	masters, etc.) are caught here and translated into friendly
	envelopes so the UI never has to display raw exception names or
	URLs.  The original exception text is logged to the server log and
	tucked into ``details_for_admin`` (only included for users with the
	``System Manager`` role) for debugging.
	"""

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	parsed_attachments = _parse_json_arg(attachments, [])
	if not isinstance(parsed_attachments, list):
		frappe.throw(_("attachments must be a JSON array"))
	confirmed = _parse_json_arg(user_confirmed_action, None)
	if confirmed is not None and not isinstance(confirmed, dict):
		frappe.throw(_("user_confirmed_action must be a JSON object"))

	from idp.llm.agent import IDPAgent

	agent = IDPAgent(doc.name)
	try:
		result = agent.run(
			user_message=content or "",
			attachments=parsed_attachments,
			user_confirmed_action=confirmed,
		)
	except Exception as exc:  # noqa: BLE001 — wide net by design
		envelope = _build_friendly_error(exc)
		logger.exception(
			"agent run failed conv=%s code=%s exc=%s",
			doc.name,
			envelope["error_code"],
			type(exc).__name__,
		)
		# Persist an assistant-side error message so the user sees
		# something in the transcript (and the chat doesn't go silent).
		try:
			err_msg = _persist_error_message(doc.name, envelope)
		except Exception:  # noqa: BLE001
			err_msg = None

		# Publish a realtime error event so any open client surfaces
		# the friendly text without polling.
		try:
			frappe.publish_realtime(
				event="idp_conversation_error",
				message={
					"conversation_id": doc.name,
					"error_code": envelope["error_code"],
					"error": envelope["friendly_message"],
				},
				user=frappe.session.user,
				after_commit=False,
			)
		except Exception:  # noqa: BLE001
			pass

		return {
			"conversation_id": doc.name,
			"iterations": 0,
			"stop_reason": "error",
			"tokens_in": 0,
			"tokens_out": 0,
			"cost_usd": 0.0,
			"new_messages": [err_msg] if err_msg else [],
			"error": envelope,
		}

	# Auto-generate title on first user message if not set yet.
	if (not doc.title or doc.title.startswith("Conversation —")) and (content or "").strip():
		preview = content.strip().splitlines()[0][:120]
		if preview:
			doc.reload()
			doc.title = preview
			doc.db_update()

	logger.info(
		"agent run conv=%s iter=%s stop=%s tokens=%s+%s cost=$%.4f",
		doc.name,
		result.iterations,
		result.stop_reason,
		result.tokens_in,
		result.tokens_out,
		result.cost_usd,
	)

	return {
		"conversation_id": doc.name,
		"iterations": result.iterations,
		"stop_reason": result.stop_reason,
		"tokens_in": result.tokens_in,
		"tokens_out": result.tokens_out,
		"cost_usd": result.cost_usd,
		"new_messages": result.new_messages,
	}


# ---------------------------------------------------------------------------
# Friendly error mapping
# ---------------------------------------------------------------------------


# (exception class name → (error_code, friendly_message)).  We key by
# class name rather than the class object so the table stays import-cheap
# even before optional modules load.
_FRIENDLY_ERROR_TABLE: dict[str, tuple[str, str]] = {
	"LLMProviderUnavailableError": (
		"LLM_UNAVAILABLE",
		"The selected AI provider is not configured. Please pick a different "
		"provider in IDP Settings or contact your administrator.",
	),
	"LLMBudgetExceededError": (
		"LLM_BUDGET_EXCEEDED",
		"The AI usage budget for today has been reached. Please try again "
		"later or ask your administrator to raise the limit.",
	),
	"LLMResponseParseError": (
		"LLM_PARSE_ERROR",
		"The AI returned an unreadable response. Please try rephrasing your "
		"request or attach the document again.",
	),
	"LLMError": (
		"LLM_ERROR",
		"The AI service ran into a problem while handling your request. "
		"Please try again in a moment.",
	),
	"OCRError": (
		"OCR_FAILED",
		"We couldn't read text from one of the attached documents. Please "
		"upload a clearer scan or a digital PDF.",
	),
	"ExtractionError": (
		"EXTRACTION_FAILED",
		"We couldn't extract structured data from the document. Please "
		"check the file format and try again.",
	),
	"UnsupportedFormatError": (
		"UNSUPPORTED_FORMAT",
		"This file format isn't supported. Please upload a PDF, image, "
		"DOCX, or XLSX file.",
	),
	"FileTooLargeError": (
		"FILE_TOO_LARGE",
		"The attached file is too large. Please upload a smaller file or "
		"split it into pages.",
	),
	"FileAliasNotFoundError": (
		"UNKNOWN_FILE",
		"The assistant referenced a file that isn't attached to this "
		"conversation. Please re-upload the document.",
	),
	"MissingMasterError": (
		"MISSING_MASTER",
		"A required master record (Supplier, Customer, or Item) was not "
		"found. Please create it first or pick an existing one.",
	),
	"MappingError": (
		"MAPPING_FAILED",
		"We couldn't match the extracted fields to an ERPNext document. "
		"Please review the extracted values and try again.",
	),
	"ValidationError": (
		"VALIDATION_FAILED",
		"The extracted data didn't pass validation. Please check the "
		"highlighted fields and resubmit.",
	),
	"RateLimitExceededError": (
		"RATE_LIMITED",
		"You've hit the rate limit for IDP processing. Please wait a moment "
		"before trying again.",
	),
	"SecurityError": (
		"SECURITY_BLOCKED",
		"This request was blocked by a security check. Please contact your "
		"administrator if you believe this is in error.",
	),
	"ConfirmationCardError": (
		"CONFIRMATION_CARD_ERROR",
		"Something went wrong while validating your edits to the "
		"confirmation card. Please reload the conversation and try again.",
	),
	"PermissionError": (
		"PERMISSION_DENIED",
		"You don't have permission to perform this action.",
	),
	"AuthenticationError": (
		"AUTH_REQUIRED",
		"Your session has expired. Please log in again.",
	),
}


def _build_friendly_error(exc: Exception) -> dict:
	"""Translate *exc* into a JSON-safe envelope for the chat UI.

	Returns a dict containing ``error_code``, ``friendly_message`` and,
	for System Managers / Administrator only, ``details_for_admin``
	carrying the raw exception class + message.
	"""

	cls_name = type(exc).__name__
	code, friendly = _FRIENDLY_ERROR_TABLE.get(
		cls_name,
		(
			"INTERNAL_ERROR",
			"Something went wrong while processing your request. Please try "
			"again. If the problem persists, contact your administrator.",
		),
	)

	envelope: dict = {
		"error_code": code,
		"friendly_message": friendly,
	}

	# Show raw details only to privileged users so end users never see
	# stack-trace-y strings, but admins can still debug from the UI.
	try:
		roles = set(frappe.get_roles(frappe.session.user))
	except Exception:  # noqa: BLE001
		roles = set()
	if "System Manager" in roles or frappe.session.user == "Administrator":
		envelope["details_for_admin"] = {
			"exception": cls_name,
			"message": str(exc)[:1000],
		}

	return envelope


def _persist_error_message(conversation_id: str, envelope: dict) -> dict | None:
	"""Append an assistant-side error message to the conversation.

	Stored as ``role=assistant`` with ``error=<friendly>`` and
	``rendered_card_type='error'`` so the frontend can render a
	distinct error bubble.  Sequence is auto-assigned by
	:meth:`IDPMessage.validate`.
	"""

	try:
		message = frappe.new_doc("IDP Message")
		message.conversation = conversation_id
		message.role = "assistant"
		message.content = envelope.get("friendly_message") or ""
		message.error = envelope.get("error_code") or "INTERNAL_ERROR"
		message.rendered_card_type = "ErrorCard"
		message.rendered_card_payload = json.dumps(envelope)
		message.created_on = frappe.utils.now_datetime()
		message.insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001
		logger.exception("failed to persist error message conv=%s", conversation_id)
		return None

	return {
		"name": message.name,
		"sequence": message.sequence,
		"role": message.role,
		"content": message.content,
		"error": message.error,
		"rendered_card_type": message.rendered_card_type,
		"rendered_card_payload": message.rendered_card_payload,
		"created_on": message.created_on,
	}


@frappe.whitelist()
def confirm_card(
	conversation_id: str,
	message_id: str,
	action: str,
	edited_payload: str | dict | None = None,
) -> dict:
	"""Phase 20 — handle a ConfirmationCard action click.

	The frontend posts the card's persisted ``message_id`` along with
	the user's chosen *action* (``submit``, ``save_draft``, ``edit``,
	``cancel``) and an optional ``edited_payload`` carrying the
	user-tweaked header / items / taxes / account mappings.

	Server responsibilities:

	* Look up the card payload originally rendered by
	  :func:`propose_create_document` and stored on the IDP Message row.
	* Validate the version, the action membership, and re-run business
	  rules on the edited payload to surface any new warnings before the
	  agent issues ``create_document``.
	* Return a structured envelope the next ``run_agent`` call uses as
	  the ``user_confirmed_action`` arg — never mutate ERPNext state
	  itself.
	"""

	from idp.core.exceptions import ConfirmationCardError
	from idp.llm.schemas import CONFIRMATION_CARD_PAYLOAD_VERSION

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not action or not isinstance(action, str):
		raise ConfirmationCardError(_("action is required"))

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	version = card.get("version")
	if version != CONFIRMATION_CARD_PAYLOAD_VERSION:
		raise ConfirmationCardError(
			_("ConfirmationCard payload version mismatch (got {0}, expected {1})").format(
				version, CONFIRMATION_CARD_PAYLOAD_VERSION
			)
		)

	allowed = {a.get("id") for a in (card.get("actions") or []) if isinstance(a, dict)}
	if action not in allowed:
		raise ConfirmationCardError(_("Action {0!r} is not permitted on this card").format(action))

	edited = _parse_json_arg(edited_payload, None)
	if edited is not None and not isinstance(edited, dict):
		raise ConfirmationCardError(_("edited_payload must be a JSON object"))

	# Re-run business rules on the edited values so the user sees fresh
	# warnings before the next agent turn fires create_document.
	revalidation: list[str] = []
	if action in {"submit", "save_draft"}:
		revalidation = _revalidate_card(card, edited)

	# Phase 24 — Cancel: just acknowledge.  The frontend handles the
	# UI-level "reset to extracted data" by re-rendering from the
	# persisted card payload, which we never mutate on cancel.
	if action == "cancel":
		logger.info("confirm_card conv=%s msg=%s action=cancel", doc.name, message.name)
		return {
			"conversation_id": doc.name,
			"message_id": message.name,
			"action": action,
			"version": version,
			"doctype": card.get("doctype"),
			"revalidation_warnings": revalidation,
			"draft_saved_message_id": None,
			"created_doc": None,
			"confirmed_payload": {
				"action": action,
				"doctype": card.get("doctype"),
				"message_id": message.name,
				"edits": edited or {},
			},
		}

	# Phase 24 — Submit and Save as Draft both actually create the
	# ERPNext document.  Submit additionally calls ``submit()`` so the
	# document leaves Draft state.  In either case the conversation's
	# uploaded attachments are linked to the newly created record.
	draft_saved_message_name: str | None = None
	created_info: dict | None = None
	if action in {"submit", "save_draft"}:
		_apply_edits_to_card(card, edited)
		try:
			created_info = _create_erpnext_doc_from_card(
				card,
				company=card.get("company") or doc.company or "",
				submit=(action == "submit"),
			)
		except Exception as exc:  # noqa: BLE001 — surface friendly error
			envelope = _build_friendly_error(exc)
			logger.exception(
				"confirm_card create failed conv=%s msg=%s action=%s",
				doc.name,
				message.name,
				action,
			)
			err_doc = _persist_error_message(doc.name, envelope)
			return {
				"conversation_id": doc.name,
				"message_id": message.name,
				"action": action,
				"version": version,
				"doctype": card.get("doctype"),
				"revalidation_warnings": revalidation,
				"draft_saved_message_id": err_doc.get("name") if err_doc else None,
				"created_doc": None,
				"error": envelope,
				"confirmed_payload": None,
			}

		# Attach the conversation's uploaded files to the created doc.
		attached = _attach_conversation_files_to_doc(
			doc,
			created_info["doctype"],
			created_info["name"],
		)
		created_info["attached_files"] = attached

		# Lock down the action buttons and stamp status onto the card
		# so the bubble renders as read-only afterwards.
		card["actions"] = []
		card["created_doc"] = created_info
		if action == "save_draft":
			card["draft_saved"] = True
		else:
			card["submitted"] = True
		message.rendered_card_payload = json.dumps(card, default=str)
		message.save(ignore_permissions=False)

		# Post a short assistant acknowledgement so the chat surface
		# reflects what happened.
		ack_text = (
			_("{0} {1} created and submitted.").format(
				created_info["doctype"], created_info["name"]
			)
			if action == "submit"
			else _("{0} {1} saved as draft.").format(
				created_info["doctype"], created_info["name"]
			)
		)
		ack_doc = frappe.new_doc("IDP Message")
		ack_doc.conversation = doc.name
		ack_doc.role = "assistant"
		ack_doc.content = ack_text
		ack_doc.rendered_card_type = "InfoCard"
		ack_doc.rendered_card_payload = json.dumps(
			{
				"card_type": "InfoCard",
				"title": _("{0} created").format(created_info["doctype"]),
				"body": ack_text,
				"link": {
					"doctype": created_info["doctype"],
					"name": created_info["name"],
				},
			},
			default=str,
		)
		ack_doc.insert(ignore_permissions=True)
		draft_saved_message_name = ack_doc.name
		try:
			frappe.publish_realtime(
				event="idp_conversation_message",
				message={"conversation": doc.name, "message": ack_doc.as_dict()},
				doctype="IDP Conversation",
				docname=doc.name,
			)
		except Exception:
			logger.debug("realtime publish skipped for confirm ack", exc_info=False)

	logger.info(
		"confirm_card conv=%s msg=%s action=%s warnings=%s created=%s",
		doc.name,
		message.name,
		action,
		len(revalidation),
		(created_info or {}).get("name"),
	)

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"action": action,
		"version": version,
		"doctype": card.get("doctype"),
		"revalidation_warnings": revalidation,
		"draft_saved_message_id": draft_saved_message_name,
		"created_doc": created_info,
		# Kept for backward-compat — the frontend used to feed this back
		# into ``run_agent`` so the agent could authorise create_document.
		# With Phase 24 the API performs the create directly, but we
		# still emit the envelope so older clients don't break.
		"confirmed_payload": {
			"action": action,
			"doctype": card.get("doctype"),
			"message_id": message.name,
			"edits": edited or {},
		},
	}


def _create_erpnext_doc_from_card(card: dict, *, company: str, submit: bool) -> dict:
	"""Build a MappedDocument from the persisted card and create the ERPNext doc.

	Args:
		card: The (already edits-applied) ConfirmationCard payload.
		company: Owning company; falls back to default if blank.
		submit: When True, also call ``doc.submit()`` after insert.

	Returns:
		``{"doctype", "name", "url", "submitted", "warnings", "created_masters"}``.
	"""

	from idp.mappers.base import MappedDocument
	from idp.mappers.document_creator import create_document as create_doc_fn

	# Header values: prefer the (possibly user-edited) card field values.
	header: dict[str, Any] = {}
	for h in card.get("header") or []:
		if not isinstance(h, dict):
			continue
		fn = h.get("fieldname")
		if not fn:
			continue
		header[fn] = h.get("value")

	# Phase 25 — non-item DocTypes (Journal Entry, Payment Entry, …)
	# stream their child rows through the same ``items`` slot on
	# :class:`MappedDocument`, but skip the Item-master enrichment
	# (``erpnext_item`` / ``is_stock_item`` are item-only concepts).
	is_item_table = (card.get("child_table_name") or "items") == "items"

	# Items: rebuild from card rows.  Apply user-picked ``erpnext_item``
	# back onto the row data as ``item_code`` so the document_creator
	# (which expects ERPNext field names) maps it correctly.  Likewise
	# carry over ``is_stock_item`` overrides set via the table.
	#
	# When the user picked an existing ERPNext item via the dropdown we
	# also pull the canonical ``item_name``/``description``/``stock_uom``
	# from the Item master so the resulting line shows the ERPNext name
	# (not the OCR-extracted string) — Phase 24 fix.  ERPNext's own
	# ``get_item_details`` hook still runs on insert to compute rate,
	# HSN, taxes, etc., so we deliberately keep the fetch minimal.
	#
	# For rows whose status is ``New`` (no existing item match) we
	# collect per-row overrides keyed by the item_code that will be
	# auto-created, so ``is_stock_item`` etc. travel through to
	# auto_create_missing_masters.
	items: list[dict] = []
	item_overrides: dict[str, dict] = {}
	items_block = card.get("items") or {}
	for r in items_block.get("rows") or []:
		if not isinstance(r, dict):
			continue
		row_data = dict(r.get("data") or {})
		# Strip Phase 25 provenance keys — they aren't ERPNext fields.
		row_data.pop("source_page", None)
		if not is_item_table:
			# Non-item child tables (Journal Entry accounts, Payment
			# Entry references, …) — forward the raw row data as-is.
			items.append(row_data)
			continue
		picked_item = r.get("erpnext_item")
		if picked_item:
			row_data["item_code"] = picked_item
			# Pull canonical fields from the Item master so the saved
			# Purchase Invoice line reflects the ERPNext item, not the
			# OCR extraction.
			master = frappe.db.get_value(
				"Item",
				picked_item,
				["item_name", "description", "stock_uom"],
				as_dict=True,
			)
			if master:
				if master.get("item_name"):
					row_data["item_name"] = master["item_name"]
				if master.get("description"):
					row_data["description"] = master["description"]
				if master.get("stock_uom") and not row_data.get("uom"):
					row_data["uom"] = master["stock_uom"]
		else:
			# Row will trigger auto-create.  The item_code in row_data
			# (set by the mapper) will be the key under which the new
			# Item is created — collect any per-row overrides here.
			pending_code = row_data.get("item_code")
			if pending_code:
				override: dict = {}
				if "is_stock_item" in row_data:
					override["is_stock_item"] = 1 if row_data.get("is_stock_item") else 0
				if row_data.get("item_name"):
					override["item_name"] = row_data["item_name"]
				if row_data.get("description"):
					override["description"] = row_data["description"]
				if row_data.get("uom"):
					override["stock_uom"] = row_data["uom"]
				if override:
					item_overrides[str(pending_code)] = override
		items.append(row_data)

	# Taxes: rebuild from card rows, using user-picked ``erpnext_account``.
	# ERPNext's ``rate`` field on Purchase/Sales Taxes and Charges is a
	# percentage (18.0, not 0.18).  The extractor sometimes returns the
	# fractional form (mirroring the OCR text) so we normalise here:
	# anything <= 1 is treated as a fraction and scaled to a percent.
	# This matches ``TaxMappingTable.formatRate`` which already does the
	# same heuristic for display (Phase 24 fix).
	taxes: list[dict] = []
	taxes_block = card.get("taxes") or {}
	for r in taxes_block.get("rows") or []:
		if not isinstance(r, dict):
			continue
		extracted = r.get("extracted") or {}
		account = r.get("erpnext_account") or extracted.get("account")
		raw_rate = extracted.get("rate")
		rate_value: float | None = None
		if raw_rate not in (None, ""):
			try:
				rate_value = float(raw_rate)
				if rate_value <= 1:
					rate_value = rate_value * 100.0
			except (TypeError, ValueError):
				rate_value = None
		taxes.append(
			{
				"account_head": account,
				"account": account,
				"rate": rate_value,
				"tax_amount": extracted.get("tax_amount"),
				"taxable_amount": extracted.get("taxable_amount"),
				"description": extracted.get("description") or account,
				"charge_type": "On Net Total",
			}
		)

	mapped = MappedDocument(
		doctype=card.get("doctype") or "",
		header=header,
		items=items,
		taxes=taxes,
	)

	result = create_doc_fn(
		mapped,
		company=company or get_default_company() or "",
		create_missing_masters=True,
		skip_validation=True,
		item_overrides=item_overrides or None,
	)

	created_doctype = result["doctype"]
	created_name = result["name"]

	if submit:
		try:
			created_doc = frappe.get_doc(created_doctype, created_name)
			created_doc.flags.ignore_permissions = True
			created_doc.submit()
		except Exception as exc:  # noqa: BLE001
			# Insert succeeded but submit failed — surface the error
			# upstream while keeping the Draft.
			logger.exception(
				"confirm_card submit failed for %s %s: %s",
				created_doctype,
				created_name,
				exc,
			)
			raise

	# Re-read so we get the latest docstatus.
	final_doc = frappe.get_doc(created_doctype, created_name)
	return {
		"doctype": final_doc.doctype,
		"name": final_doc.name,
		"url": frappe.utils.get_url_to_form(final_doc.doctype, final_doc.name),
		"submitted": bool(submit),
		"docstatus": int(getattr(final_doc, "docstatus", 0) or 0),
		"warnings": result.get("warnings") or [],
		"created_masters": result.get("created_masters") or [],
	}


def _attach_conversation_files_to_doc(
	conversation_doc: "frappe.Document",
	target_doctype: str,
	target_name: str,
) -> list[dict]:
	"""Link every uploaded conversation attachment to *target_doctype/name*.

	We don't duplicate the ``tabFile`` row — instead we insert a fresh
	``File`` row for the target that points at the same ``file_url``,
	preserving the original file binary and keeping ``attached_to_*``
	correctly set.  Returns metadata about the attached files.
	"""

	out: list[dict] = []
	for att in conversation_doc.attachments or []:
		try:
			file_url = att.file_url
			if not file_url:
				continue
			file_doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_url": file_url,
					"file_name": att.file_name or file_url.rsplit("/", 1)[-1],
					"attached_to_doctype": target_doctype,
					"attached_to_name": target_name,
					"is_private": 1 if (file_url or "").startswith("/private/") else 0,
				}
			)
			file_doc.flags.ignore_permissions = True
			# ``ignore_duplicate_entry_error`` keeps re-runs idempotent if
			# the user re-clicks Submit on a previously failed attempt.
			try:
				file_doc.insert(ignore_permissions=True)
			except Exception as exc:  # noqa: BLE001
				logger.warning(
					"attach file %s to %s/%s failed: %s",
					file_url,
					target_doctype,
					target_name,
					exc,
				)
				continue
			out.append(
				{
					"file_url": file_url,
					"file_name": att.file_name,
					"attached_to": f"{target_doctype}/{target_name}",
				}
			)
		except Exception:  # noqa: BLE001
			logger.exception(
				"unexpected failure attaching %s to %s/%s",
				getattr(att, "file_url", "?"),
				target_doctype,
				target_name,
			)
	return out


def _apply_edits_to_card(card: dict, edited: dict | None) -> None:
	"""Mutate *card* in-place to reflect the user's confirmation edits.

	Only the bits the UI surfaces today are honoured: header field
	values, item-row mappings (``erpnext_item``), tax-row mappings
	(``erpnext_account``), and per-item ``is_stock_item`` overrides.
	The rest of the payload is left intact so re-rendering keeps its
	candidate lists, scores, and warnings.
	"""

	if not isinstance(edited, dict):
		return

	header_edits = edited.get("header") or {}
	if isinstance(header_edits, dict) and header_edits:
		for h in card.get("header") or []:
			if not isinstance(h, dict):
				continue
			fn = h.get("fieldname")
			if fn in header_edits:
				h["value"] = header_edits[fn]

	item_map = edited.get("item_mappings") or {}
	stock_overrides = edited.get("item_stock_overrides") or {}
	# Phase 25 — Generic child-row edits.  Shape:
	# ``{row_index: {fieldname: value, ...}}``.  Applied for every card,
	# but the GenericChildTable UI is the primary producer (non-item
	# DocTypes); the item table also uses it for the "Apply to all
	# rows" UOM action.
	row_edits = edited.get("row_edits") or {}
	items_block = card.get("items") or {}
	for r in items_block.get("rows") or []:
		if not isinstance(r, dict):
			continue
		idx = r.get("index")
		if idx is None:
			continue
		key = str(idx)
		if isinstance(item_map, dict) and (key in item_map or idx in item_map):
			r["erpnext_item"] = item_map.get(key) or item_map.get(idx)
			r["status"] = "Existing" if r["erpnext_item"] else "New"
		if isinstance(stock_overrides, dict) and (key in stock_overrides or idx in stock_overrides):
			val = stock_overrides.get(key)
			if val is None:
				val = stock_overrides.get(idx)
			data = r.get("data") or {}
			data["is_stock_item"] = bool(val)
			r["data"] = data
		if isinstance(row_edits, dict) and (key in row_edits or idx in row_edits):
			patch = row_edits.get(key) or row_edits.get(idx) or {}
			if isinstance(patch, dict) and patch:
				data = dict(r.get("data") or {})
				for fn, val in patch.items():
					if not fn:
						continue
					data[fn] = val
				r["data"] = data

	account_map = edited.get("account_mappings") or {}
	taxes_block = card.get("taxes") or {}
	for r in taxes_block.get("rows") or []:
		if not isinstance(r, dict):
			continue
		idx = r.get("row_index")
		if idx is None:
			continue
		key = str(idx)
		if isinstance(account_map, dict) and (key in account_map or idx in account_map):
			r["erpnext_account"] = account_map.get(key) or account_map.get(idx)
			r["status"] = "Existing" if r["erpnext_account"] else "New"


@frappe.whitelist()
def get_card_items_page(
	conversation_id: str,
	message_id: str,
	page: int = 1,
	page_size: int = 10,
) -> dict:
	"""Phase 20 — paginated access to a ConfirmationCard's ``items.rows``.

	The card payload only ships the first page (default 10 rows) to
	keep the chat message size predictable.  This endpoint serves
	subsequent pages straight off the persisted card payload.
	"""

	from idp.core.exceptions import ConfirmationCardError

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	try:
		page = max(1, int(page or 1))
		# Phase 25 — accept the admin-tuned default from IDP Settings.
		page_size_raw = page_size if page_size not in (None, 0, "0") else _settings_page_size_default()
		page_size = max(1, min(int(page_size_raw or 10), 100))
	except (TypeError, ValueError):
		raise ConfirmationCardError(_("page and page_size must be integers")) from None

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	# The persisted card only stores page 1 inline — for deeper pages we
	# fall back to the raw items list serialised in the tool result, if
	# available.  Phase 20 keeps both around so we can render any page
	# without re-running the LLM.
	tool_result = _parse_json_arg(message.tool_result, None) or {}
	tool_args = _parse_json_arg(message.tool_arguments, None) or {}
	source_items = tool_args.get("items") or []
	total = len(source_items) or (card.get("items") or {}).get("total") or 0

	start = (page - 1) * page_size
	end = start + page_size
	slice_rows = source_items[start:end] if isinstance(source_items, list) else []

	# Phase 25 — extract source_page per row for traceability.
	source_page_keys = ("source_page", "page", "page_number", "pdf_page", "_page")

	def _row_source_page(row: dict) -> int | None:
		for key in source_page_keys:
			v = row.get(key)
			if v in (None, ""):
				continue
			try:
				n = int(v)
			except (TypeError, ValueError):
				continue
			if n > 0:
				return n
		return None

	rendered = []
	for offset, row in enumerate(slice_rows):
		if not isinstance(row, dict):
			continue
		rendered.append(
			{
				"index": start + offset,
				"data": row,
				"source_page": _row_source_page(row),
			}
		)

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"page": page,
		"page_size": page_size,
		"total": total,
		"has_more": end < total,
		"rows": rendered,
		# Echo the tool_result data block for any debug consumers.
		"diagnostic": {
			"tool_result_data": tool_result.get("data") if isinstance(tool_result, dict) else None,
		},
	}


def _settings_page_size_default() -> int | None:
	"""Read ``IDP Settings.confirmation_page_size`` with a safe fallback."""

	try:
		from idp.core.config import get_idp_settings
	except Exception:
		return None
	try:
		settings = get_idp_settings() or {}
	except Exception:
		return None
	raw = settings.get("confirmation_page_size")
	if raw in (None, "", 0):
		return None
	try:
		return max(1, int(raw))
	except (TypeError, ValueError):
		return None


def _revalidate_card(card: dict, edited: dict | None) -> list[str]:
	"""Apply user edits onto the card snapshot and re-run business rules.

	* ``edited.header``: dict overriding header field values.
	* ``edited.items``: list[dict] replacing the items rows wholesale.
	* ``edited.taxes``: list[dict] replacing the tax rows wholesale.
	* ``edited.account_mappings``: ``{row_index: account_name}`` —
	  resolves user-picked ``erpnext_account`` for each tax row.
	"""

	try:
		from idp.mappers.base import MappedDocument
		from idp.validators.business_rules import validate_business_rules
	except Exception:
		return []

	header = {}
	for h in card.get("header") or []:
		if isinstance(h, dict) and h.get("fieldname"):
			header[h["fieldname"]] = h.get("value")

	# Items — pull from the card snapshot's first page and the persisted
	# card never holds beyond ``items.total`` on its own; we trust the
	# user edits to be the full set when provided.
	items_block = card.get("items") or {}
	items = [r.get("data") for r in (items_block.get("rows") or []) if isinstance(r, dict)]

	taxes_block = card.get("taxes") or {}
	taxes = []
	for r in taxes_block.get("rows") or []:
		if not isinstance(r, dict):
			continue
		extracted = r.get("extracted") or {}
		taxes.append(
			{
				"account": r.get("erpnext_account") or extracted.get("account"),
				"rate": extracted.get("rate"),
				"tax_amount": extracted.get("tax_amount"),
				"taxable_amount": extracted.get("taxable_amount"),
				"description": extracted.get("description"),
			}
		)

	if isinstance(edited, dict):
		if isinstance(edited.get("header"), dict):
			header.update(edited["header"])
		if isinstance(edited.get("items"), list):
			items = edited["items"]
		if isinstance(edited.get("taxes"), list):
			taxes = edited["taxes"]
		mappings = edited.get("account_mappings") or {}
		if isinstance(mappings, dict):
			for raw_idx, account in mappings.items():
				try:
					i = int(raw_idx)
				except (TypeError, ValueError):
					continue
				if 0 <= i < len(taxes) and isinstance(taxes[i], dict) and account:
					taxes[i]["account"] = account

	mapped = MappedDocument(
		doctype=card.get("doctype") or "",
		header=header,
		items=[r for r in items if isinstance(r, dict)],
		taxes=[r for r in taxes if isinstance(r, dict)],
	)
	try:
		return validate_business_rules(mapped, card.get("company") or "")
	except Exception:
		return []


@frappe.whitelist()
def get_chat_defaults() -> dict:
	"""Return defaults used to seed a fresh chatbot conversation.

	Pulled from IDP Settings (provider/model/languages/target doctype)
	plus the user's default company.  Any field not yet configured in
	IDP Settings falls back to a hard-coded constant from
	``idp.core.constants`` so the frontend can always quick-start a
	conversation without showing the New Conversation modal.

	The ``defaults_source`` map tells the frontend which fields came
	from IDP Settings vs. the in-code fallbacks, in case the UI wants
	to nudge the admin to set them explicitly.
	"""

	_require_login()

	from idp.core.config import get_default_company, get_idp_settings
	from idp.core.constants import (
		DEFAULT_CHAT_LLM_MODEL,
		DEFAULT_CHAT_LLM_PROVIDER,
		DEFAULT_CHAT_OCR_LANGUAGE,
		DEFAULT_CHAT_OUTPUT_LANGUAGE,
		DEFAULT_CHAT_TARGET_DOCTYPE,
	)

	settings = get_idp_settings()

	def _pick(setting_key: str, fallback: str) -> tuple[str, str]:
		value = (settings.get(setting_key) or "").strip()
		if value:
			return value, "settings"
		return fallback, "fallback"

	provider, provider_src = _pick("llm_provider", DEFAULT_CHAT_LLM_PROVIDER)
	model, model_src = _pick("llm_model", DEFAULT_CHAT_LLM_MODEL)
	target, target_src = _pick("default_target_doctype", DEFAULT_CHAT_TARGET_DOCTYPE)
	ocr_lang, ocr_src = _pick("default_ocr_language", DEFAULT_CHAT_OCR_LANGUAGE)
	out_lang, out_src = _pick("default_output_language", DEFAULT_CHAT_OUTPUT_LANGUAGE)

	defaults = {
		"llm_provider": provider,
		"llm_model": model,
		"target_doctype": target,
		"ocr_language": ocr_lang,
		"output_language": out_lang,
		"company": get_default_company() or "",
		"defaults_source": {
			"llm_provider": provider_src,
			"llm_model": model_src,
			"target_doctype": target_src,
			"ocr_language": ocr_src,
			"output_language": out_src,
		},
	}
	# Always ready — fallbacks fill any gap in IDP Settings.
	defaults["ready"] = True
	# ``missing`` lists fields that came from the fallback (not from
	# IDP Settings) so the admin can be nudged to configure them.
	defaults["missing"] = [
		key
		for key in ("llm_provider", "llm_model", "target_doctype")
		if defaults["defaults_source"][key] == "fallback"
	]
	return defaults


@frappe.whitelist()
def list_agent_tools() -> list[dict]:
	"""Return the registered Phase 19 tools (for diagnostics / UI hints)."""

	_require_login()
	from idp.llm.tools.registry import list_tools

	return [
		{
			"name": t.name,
			"description": t.description,
			"mutating": t.mutating,
			"requires_role": t.requires_role,
		}
		for t in list_tools()
	]


# ---------------------------------------------------------------------------
# Phase 24 — Item / Tax remap endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def search_items(query: str, top_n: int = 10) -> list[dict]:
	"""Phase 24 — interactive Item search for the mapping table.

	The user can pick an alternate ``ERPNext Item`` for any row whose
	auto-match landed on ``status = "New"``.  This endpoint surfaces
	the full :func:`match_single_item` candidate list so the UI can
	render a search dropdown without round-tripping the LLM.
	"""

	_require_login()
	query = (query or "").strip()
	if not query:
		return []
	try:
		top_n = max(1, min(int(top_n or 10), 50))
	except (TypeError, ValueError):
		top_n = 10

	from idp.mappers.item_matcher import match_single_item

	# Use a deliberately low floor so even partial substrings show up
	# in the search dropdown — the UI sorts and filters from there.
	result = match_single_item(
		{"item_code": query, "item_name": query},
		match_threshold=0.99,  # ensures status stays "New" for ranking
		floor_threshold=0.3,
		top_n=top_n,
	)
	return [c.to_dict() for c in result.matches]


@frappe.whitelist()
def search_accounts(query: str, company: str | None = None, top_n: int = 10) -> list[dict]:
	"""Phase 24 — interactive Account search for the tax mapping table."""

	_require_login()
	query = (query or "").strip()
	if not query:
		return []
	try:
		top_n = max(1, min(int(top_n or 10), 50))
	except (TypeError, ValueError):
		top_n = 10

	from idp.mappers.tax_matcher import match_single_tax

	result = match_single_tax(
		{"account": query},
		company=company,
		match_threshold=0.99,
		floor_threshold=0.3,
		top_n=top_n,
	)
	return [c.to_dict() for c in result.matches]


@frappe.whitelist()
def remap_card_row(
	conversation_id: str,
	message_id: str,
	row_kind: str,
	row_index: int,
	action: str,
	target: str | None = None,
) -> dict:
	"""Phase 24 §24.5 — apply a user remap onto a persisted ConfirmationCard.

	Args:
		conversation_id: Owning conversation.
		message_id: ``IDP Message`` carrying the card payload.
		row_kind: Either ``"items"`` or ``"taxes"``.
		row_index: Zero-based index in the (full) row list.
		action: One of ``"pick"`` (set ``erpnext_*`` to ``target``),
			``"mark_new"`` (clear mapping, force ``status = "New"``),
			``"accept"`` (no-op confirmation; persists the row's current
			best match and clears the candidate list).
		target: Required for ``action = "pick"`` — the chosen
			``Item.name`` / ``Account.name``.

	Returns the updated row dict (same shape as the card payload row).
	"""

	from idp.core.exceptions import ConfirmationCardError

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	row_kind = (row_kind or "").strip().lower()
	if row_kind not in ("items", "taxes"):
		raise ConfirmationCardError(_("row_kind must be 'items' or 'taxes'"))

	action = (action or "").strip().lower()
	if action not in ("pick", "mark_new", "accept"):
		raise ConfirmationCardError(_("action must be 'pick', 'mark_new', or 'accept'"))

	try:
		row_index = int(row_index)
		if row_index < 0:
			raise ValueError
	except (TypeError, ValueError):
		raise ConfirmationCardError(_("row_index must be a non-negative integer")) from None

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	block = card.get(row_kind)
	if not isinstance(block, dict):
		raise ConfirmationCardError(_("Card has no {kind} block").format(kind=row_kind))

	rows = block.get("rows") or []
	# Find the row by ``index`` / ``row_index`` since ``rows`` may only
	# carry the inline page (Phase 25 pagination).
	idx_key = "index" if row_kind == "items" else "row_index"
	target_row = None
	for r in rows:
		if isinstance(r, dict) and r.get(idx_key) == row_index:
			target_row = r
			break
	if target_row is None:
		raise ConfirmationCardError(
			_("Row {idx} not found in {kind} block").format(idx=row_index, kind=row_kind)
		)

	resolved_field = "erpnext_item" if row_kind == "items" else "erpnext_account"

	if action == "mark_new":
		target_row[resolved_field] = None
		target_row["status"] = "New"
		target_row["match_reason"] = None
		target_row["confidence"] = 0.0
	elif action == "pick":
		if not target:
			raise ConfirmationCardError(_("target is required for action='pick'"))
		target_row[resolved_field] = str(target)
		target_row["status"] = "Existing"
		target_row["match_reason"] = "user_picked"
		target_row["confidence"] = 1.0
	elif action == "accept":
		# Confirm whatever is already there — collapse the candidate list
		# but keep the resolved value & status as-is.
		if target_row.get(resolved_field):
			target_row["status"] = "Existing"
			if not target_row.get("match_reason"):
				target_row["match_reason"] = "user_accepted"

	# Persist the mutated card payload.
	message.rendered_card_payload = json.dumps(card)
	message.save(ignore_permissions=False)
	frappe.db.commit()

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"row_kind": row_kind,
		"row_index": row_index,
		"row": target_row,
	}


@frappe.whitelist()
def create_item_from_row(
	conversation_id: str,
	message_id: str,
	row_index: int,
	defaults: str | dict | None = None,
) -> dict:
	"""Phase 24 §24.6 — auto-create a minimal Item from an extracted row.

	Permission: requires the ``IDP Master Creator`` role (Phase 21) or
	the standard Frappe ``create`` permission on Item.  Either gate is
	sufficient.

	The new Item picks defaults from the row's extracted data (item_name,
	stock_uom, is_stock_item, is_fixed_asset).  After creation the
	matching row in the persisted ConfirmationCard is flipped to
	``status = "Existing"`` and ``erpnext_item`` is set to the new
	Item's name.
	"""

	from idp.core.exceptions import ConfirmationCardError
	from idp.mappers.document_creator import _create_item

	user = _require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	user_roles = set(frappe.get_roles(user))
	if "IDP Master Creator" not in user_roles and not frappe.has_permission("Item", ptype="create"):
		frappe.throw(
			_("You need the 'IDP Master Creator' role or create permission on Item."),
			frappe.PermissionError,
		)

	try:
		row_index = int(row_index)
		if row_index < 0:
			raise ValueError
	except (TypeError, ValueError):
		raise ConfirmationCardError(_("row_index must be a non-negative integer")) from None

	defaults_dict = _parse_json_arg(defaults, {}) or {}
	if not isinstance(defaults_dict, dict):
		raise ConfirmationCardError(_("defaults must be a JSON object"))

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	items_block = card.get("items") or {}
	rows = items_block.get("rows") or []
	target_row = next(
		(r for r in rows if isinstance(r, dict) and r.get("index") == row_index),
		None,
	)
	if target_row is None:
		raise ConfirmationCardError(
			_("Item row {idx} not found in card").format(idx=row_index)
		)

	row_data = target_row.get("data") or {}
	proposed_name = (
		str(row_data.get("item_name") or row_data.get("item") or row_data.get("item_code") or "").strip()
	)
	if not proposed_name:
		raise ConfirmationCardError(_("Row has no item name to create from"))

	settings: dict[str, Any] = {
		"stock_uom": defaults_dict.get("stock_uom") or row_data.get("uom") or "Nos",
		"item_group": defaults_dict.get("item_group", "All Item Groups"),
		"is_stock_item": int(
			defaults_dict.get("is_stock_item")
			if defaults_dict.get("is_stock_item") is not None
			else (row_data.get("is_stock_item") or 0)
		),
		"is_fixed_asset": int(defaults_dict.get("is_fixed_asset", 0)),
	}

	# If the Item already exists (race / explicit naming), short-circuit.
	if frappe.db.exists("Item", proposed_name):
		new_name = proposed_name
	else:
		_create_item(proposed_name, get_default_company(), settings)
		new_name = proposed_name

	# Flip the row in the persisted card.
	target_row["erpnext_item"] = new_name
	target_row["status"] = "Existing"
	target_row["match_reason"] = "auto_created"
	target_row["confidence"] = 1.0
	message.rendered_card_payload = json.dumps(card)
	message.save(ignore_permissions=False)
	frappe.db.commit()

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"row_index": row_index,
		"item_code": new_name,
		"row": target_row,
	}


# ---------------------------------------------------------------------------
# Phase 25 — Bulk / Mass-edit helpers for large item sets
# ---------------------------------------------------------------------------


@frappe.whitelist()
def bulk_match_items(
	conversation_id: str,
	message_id: str,
	match_threshold: float | str = 0.6,
	only_unmatched: int | str | bool = 1,
) -> dict:
	"""Phase 25 §25.4 — re-run the §24.1 item matcher with a looser threshold.

	Walks the full ``items`` list from the original tool arguments
	(persisted alongside the ConfirmationCard) and updates every row in
	the persisted card whose ``status == "New"`` (or every row when
	``only_unmatched=False``).  Rows whose best score clears the looser
	``match_threshold`` are flipped to ``Existing`` with the new resolved
	Item name; otherwise the candidate list is refreshed so the user
	can pick from a richer dropdown.

	Returns a summary ``{matched, refreshed, unchanged, total}``.
	"""

	from idp.core.exceptions import ConfirmationCardError

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	try:
		threshold = float(match_threshold)
	except (TypeError, ValueError):
		threshold = 0.6
	threshold = max(0.0, min(threshold, 1.0))

	only_unmatched_flag = str(only_unmatched).lower() not in ("0", "false", "no", "")

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	# Phase 25 only re-matches when the card is item-bearing; otherwise
	# silently no-op so the UI can safely surface the button on every
	# card (it just won't do anything for, say, Journal Entry).
	if (card.get("child_table_name") or "items") != "items":
		return {
			"conversation_id": doc.name,
			"message_id": message.name,
			"matched": 0,
			"refreshed": 0,
			"unchanged": 0,
			"total": 0,
			"skipped_reason": "non_item_doctype",
		}

	from idp.mappers.item_matcher import match_items

	tool_args = _parse_json_arg(message.tool_arguments, None) or {}
	source_items: list[dict] = list(tool_args.get("items") or [])

	# Run a fresh matcher pass over the full extracted set.  The looser
	# ``match_threshold`` means rows that previously fell to "New" can
	# now bind to their top candidate when its score >= threshold.
	results = match_items(source_items, match_threshold=threshold, floor_threshold=0.3)

	# Index existing rows by their ``index`` field so we can update both
	# the inline first page and the persisted card payload (the latter
	# only carries page 1 — but persisted updates still need to flow
	# through ``confirm_card`` via the tool args anyway).
	items_block = card.get("items") or {}
	rows = items_block.get("rows") or []
	by_index = {r.get("index"): r for r in rows if isinstance(r, dict) and r.get("index") is not None}

	matched = 0
	refreshed = 0
	unchanged = 0

	for idx, result in enumerate(results):
		target_row = by_index.get(idx)
		if target_row is None:
			# Row is beyond page 1 — nothing to update inline; the
			# persisted source items still drive deeper pages and will
			# be re-matched on the next card render.
			continue
		current_status = target_row.get("status") or "New"
		if only_unmatched_flag and current_status == "Existing":
			unchanged += 1
			continue

		candidates = [c.to_dict() for c in result.matches]
		target_row["match_candidates"] = candidates
		target_row["item_mapping_suggestions"] = [
			{
				"name": c.get("item_code"),
				"label": c.get("item_name"),
				"score": c.get("score"),
			}
			for c in candidates
		]

		if result.status == "Existing" and result.best_match:
			target_row["erpnext_item"] = result.best_match
			target_row["status"] = "Existing"
			target_row["match_reason"] = result.match_reason or "bulk_match"
			target_row["confidence"] = result.confidence
			matched += 1
		else:
			# Still no match — but candidates refreshed.
			target_row["match_reason"] = result.match_reason or target_row.get("match_reason")
			target_row["confidence"] = result.confidence
			refreshed += 1

	# Persist the updated card.
	message.rendered_card_payload = json.dumps(card)
	message.save(ignore_permissions=False)
	frappe.db.commit()

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"matched": matched,
		"refreshed": refreshed,
		"unchanged": unchanged,
		"total": len(results),
		"match_threshold": threshold,
		"rendered_card_payload": message.rendered_card_payload,
	}


@frappe.whitelist()
def apply_to_all_rows(
	conversation_id: str,
	message_id: str,
	fieldname: str,
	value: str | None = None,
	row_kind: str = "items",
) -> dict:
	"""Phase 25 §25.4 — apply *value* to *fieldname* on every row.

	Common use cases: bulk-set ``uom`` to ``Nos``, bulk-set
	``is_stock_item`` to ``0`` across a Service Invoice.  Operates on
	the inline rows of the persisted card payload.
	"""

	from idp.core.exceptions import ConfirmationCardError

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	fieldname = (fieldname or "").strip()
	if not fieldname:
		raise ConfirmationCardError(_("fieldname is required"))

	row_kind = (row_kind or "items").strip().lower()
	if row_kind not in ("items", "taxes"):
		raise ConfirmationCardError(_("row_kind must be 'items' or 'taxes'"))

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	block = card.get(row_kind) or {}
	rows = block.get("rows") or []
	updated = 0
	for r in rows:
		if not isinstance(r, dict):
			continue
		if row_kind == "items":
			data = dict(r.get("data") or {})
			data[fieldname] = value
			r["data"] = data
		else:
			# Taxes use the ``extracted`` sub-dict.
			extracted = dict(r.get("extracted") or {})
			extracted[fieldname] = value
			r["extracted"] = extracted
		updated += 1

	message.rendered_card_payload = json.dumps(card)
	message.save(ignore_permissions=False)
	frappe.db.commit()

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"row_kind": row_kind,
		"fieldname": fieldname,
		"value": value,
		"updated": updated,
		"rendered_card_payload": message.rendered_card_payload,
	}


@frappe.whitelist()
def bulk_accept_suggestions(
	conversation_id: str,
	message_id: str,
) -> dict:
	"""Phase 25 §25.4 — accept the top candidate for every unresolved row.

	Walks the inline rows of the persisted card and, for any row whose
	``status == "New"`` with a non-empty ``match_candidates`` list,
	picks the highest-scoring candidate and flips the row to
	``Existing``.  Useful when the user trusts the matcher's first
	guess across the whole table.
	"""

	from idp.core.exceptions import ConfirmationCardError

	_require_login()
	doc = _load_conversation(conversation_id)
	if not frappe.has_permission("IDP Conversation", ptype="write", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	message = frappe.get_doc("IDP Message", message_id)
	if message.conversation != doc.name:
		raise ConfirmationCardError(_("Message does not belong to this conversation"))

	card = _parse_json_arg(message.rendered_card_payload, None)
	if not isinstance(card, dict):
		raise ConfirmationCardError(_("Message does not carry a confirmation card"))

	if (card.get("child_table_name") or "items") != "items":
		return {
			"conversation_id": doc.name,
			"message_id": message.name,
			"accepted": 0,
			"skipped_reason": "non_item_doctype",
		}

	items_block = card.get("items") or {}
	rows = items_block.get("rows") or []
	accepted = 0
	for r in rows:
		if not isinstance(r, dict):
			continue
		if (r.get("status") or "New") == "Existing":
			continue
		candidates = r.get("match_candidates") or []
		if not candidates:
			continue
		# Already sorted by score descending — pick the first.
		top = candidates[0]
		pick = top.get("item_code") if isinstance(top, dict) else None
		if not pick:
			continue
		r["erpnext_item"] = pick
		r["status"] = "Existing"
		r["match_reason"] = "bulk_accepted"
		r["confidence"] = top.get("score") if isinstance(top, dict) else None
		accepted += 1

	message.rendered_card_payload = json.dumps(card)
	message.save(ignore_permissions=False)
	frappe.db.commit()

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"accepted": accepted,
		"rendered_card_payload": message.rendered_card_payload,
	}
