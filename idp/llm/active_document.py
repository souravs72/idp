# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Active-document context for the chat agent.

The "active document" is the ERPNext record the user is currently
working on inside an :doctype:`IDP Conversation`.  Stamping it on the
conversation lets the system prompt include the doc's parent context
(company, party) on every turn, which kills the speculative
``search_documents`` call the LLM otherwise makes to find the doc's
own ``company`` before invoking ``update_document``.

This module is the single source of truth for:

* writing the stamp (:func:`set_active_document`) — called by tools
  that operate on a specific record,
* reading the stamp (:func:`get_active_document`) — called by the
  agent loop when building the system prompt,
* rendering the prompt-side context block (:func:`render_context_block`).
"""

from __future__ import annotations

from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.llm.active_document")


# A small, fixed set of fields we try to surface on the system prompt.
# Different doctypes use different names for the same concept (party,
# date, total) — pulling them all in one go keeps the prompt builder
# stateless and the DB hit small.
_INTERESTING_FIELDS: tuple[str, ...] = (
	"company",
	"supplier",
	"customer",
	"party",
	"party_name",
	"posting_date",
	"transaction_date",
	"bill_no",
	"reference_no",
	"grand_total",
	"status",
)


def set_active_document(conversation_id: str, doctype: str, name: str) -> None:
	"""Stamp *doctype/name* as the active document on *conversation_id*.

	Best-effort: any Frappe error is logged and swallowed because the
	stamp is advisory — the chat loop must never fail because the active
	doc could not be persisted.
	"""

	if not (conversation_id and doctype and name):
		return
	try:
		import frappe

		current = frappe.db.get_value(
			"IDP Conversation",
			conversation_id,
			["active_document_doctype", "active_document_name"],
			as_dict=True,
		)
		if current and current.get("active_document_doctype") == doctype and current.get("active_document_name") == name:
			return  # No-op when the stamp already matches.

		frappe.db.set_value(
			"IDP Conversation",
			conversation_id,
			{
				"active_document_doctype": doctype,
				"active_document_name": name,
			},
			update_modified=False,
		)
	except Exception:
		logger.debug("set_active_document failed", exc_info=True)


def get_active_document(conversation_id: str) -> dict[str, Any] | None:
	"""Return the active doc identity + a small bag of contextual fields.

	The returned dict has shape::

	    {
	        "doctype": str,
	        "name": str,
	        "fields": {"company": ..., "supplier": ..., ...},  # only present keys
	    }

	Returns ``None`` when no active document is set or the record no
	longer exists.  All Frappe failures degrade to ``None`` because the
	context block is purely additive.
	"""

	if not conversation_id:
		return None
	try:
		import frappe

		row = frappe.db.get_value(
			"IDP Conversation",
			conversation_id,
			["active_document_doctype", "active_document_name"],
			as_dict=True,
		)
		if not row:
			return None
		doctype = row.get("active_document_doctype")
		name = row.get("active_document_name")
		if not (doctype and name):
			return None
		if not frappe.db.exists(doctype, name):
			return None

		meta = frappe.get_meta(doctype)
		present = {f.fieldname for f in meta.fields}
		select = [f for f in _INTERESTING_FIELDS if f in present]
		fields: dict[str, Any] = {}
		if select:
			values = frappe.db.get_value(doctype, name, select, as_dict=True) or {}
			fields = {k: v for k, v in values.items() if v not in (None, "")}
		return {"doctype": doctype, "name": name, "fields": fields}
	except Exception:
		logger.debug("get_active_document failed", exc_info=True)
		return None


def render_context_block(active: dict[str, Any] | None) -> str:
	"""Return the system-prompt fragment for *active*, or empty string.

	The format is intentionally one line per fact so the LLM cannot
	confuse the active doc's parent context with the user's free-form
	chat history.
	"""

	if not active or not active.get("doctype") or not active.get("name"):
		return ""
	parts = [
		f"Active document: {active['doctype']} \"{active['name']}\"",
	]
	for key, value in (active.get("fields") or {}).items():
		parts.append(f"  - {key}: {value}")
	parts.append(
		"When the user asks about \"this invoice / record / cost center / supplier\","
		" assume they mean the active document above."
		" Call update_document / compare_document / get_document directly on it"
		" without first searching for it."
	)
	return "\n".join(parts)


__all__ = [
	"get_active_document",
	"render_context_block",
	"set_active_document",
]
