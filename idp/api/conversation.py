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
