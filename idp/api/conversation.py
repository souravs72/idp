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

import frappe
from frappe import _

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

	from idp.idp.llm.agent import IDPAgent

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
	from idp.idp.llm.schemas import CONFIRMATION_CARD_PAYLOAD_VERSION

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

	logger.info(
		"confirm_card conv=%s msg=%s action=%s warnings=%s",
		doc.name,
		message.name,
		action,
		len(revalidation),
	)

	return {
		"conversation_id": doc.name,
		"message_id": message.name,
		"action": action,
		"version": version,
		"doctype": card.get("doctype"),
		"revalidation_warnings": revalidation,
		# The frontend hands this back to ``run_agent`` so the agent can
		# authorise the next ``create_document`` invocation.
		"confirmed_payload": {
			"action": action,
			"doctype": card.get("doctype"),
			"message_id": message.name,
			"edits": edited or {},
		},
	}


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
		page_size = max(1, min(int(page_size or 10), 100))
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

	rendered = []
	for offset, row in enumerate(slice_rows):
		if not isinstance(row, dict):
			continue
		rendered.append({"index": start + offset, "data": row})

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


def _revalidate_card(card: dict, edited: dict | None) -> list[str]:
	"""Apply user edits onto the card snapshot and re-run business rules.

	* ``edited.header``: dict overriding header field values.
	* ``edited.items``: list[dict] replacing the items rows wholesale.
	* ``edited.taxes``: list[dict] replacing the tax rows wholesale.
	* ``edited.account_mappings``: ``{row_index: account_name}`` —
	  resolves user-picked ``erpnext_account`` for each tax row.
	"""

	try:
		from idp.idp.mappers.base import MappedDocument
		from idp.idp.validators.business_rules import validate_business_rules
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
	plus the user's default company.  The frontend uses this to skip
	the "New Conversation" modal when every required field is filled.
	"""

	_require_login()

	from idp.core.config import get_default_company, get_idp_settings

	settings = get_idp_settings()
	defaults = {
		"llm_provider": settings.get("llm_provider") or "",
		"llm_model": settings.get("llm_model") or "",
		"target_doctype": settings.get("default_target_doctype") or "",
		"ocr_language": settings.get("default_ocr_language") or "en",
		"output_language": settings.get("default_output_language") or "English",
		"company": get_default_company() or "",
	}
	# A conversation is "ready" if we have at least a provider+model and
	# a target doctype; the company can usually be resolved per request.
	defaults["ready"] = bool(
		defaults["llm_provider"]
		and defaults["llm_model"]
		and defaults["target_doctype"]
	)
	defaults["missing"] = [
		key
		for key in ("llm_provider", "llm_model", "target_doctype")
		if not defaults[key]
	]
	return defaults


@frappe.whitelist()
def list_agent_tools() -> list[dict]:
	"""Return the registered Phase 19 tools (for diagnostics / UI hints)."""

	_require_login()
	from idp.idp.llm.tools.registry import list_tools

	return [
		{
			"name": t.name,
			"description": t.description,
			"mutating": t.mutating,
			"requires_role": t.requires_role,
		}
		for t in list_tools()
	]
