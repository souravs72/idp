# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 32 — Reversibility (Undo) via Frappe permissions.

Surfaces a short window during which the user who just confirmed a
ConfirmationCard can roll the resulting ERPNext document back without
opening the form.  Drafts are deleted outright; submitted documents
that support cancellation are cancelled; everything else (anything
already amended, paid, or otherwise depended on) is refused with a
friendly explanation rather than an opaque permission error.

Authorisation rules:

* The originating session user (``IDP Conversation.owner``) may always
  undo within the window.
* Members of ``System Manager`` may undo on behalf of any user, so
  admins can mop up after a bad batch run.
* Everyone else gets ``PermissionError`` — the chatbot UI maps this to
  the Phase 31 unified error envelope.

The window itself is governed by ``IDP Settings.undo_window_minutes``
(default 5).  A value of 0 disables the entire endpoint so deployments
with strict audit requirements can opt out.
"""

from __future__ import annotations

import frappe
from frappe import _

from idp.core.audit import log_event
from idp.core.logger import get_logger

logger = get_logger("idp.api.undo")


# Submittable docstatus values.  ``docstatus`` is an int in Frappe:
# 0 = Draft, 1 = Submitted, 2 = Cancelled.  Anything > 1 means the
# document has already been cancelled (or is amended) so undo is a
# no-op / impossible.
_DRAFT = 0
_SUBMITTED = 1
_CANCELLED = 2


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------


def get_undo_window_minutes() -> int:
	"""Return the configured undo window in minutes, defaulting to 5.

	0 (or a negative value) means the feature is disabled.  We never
	raise here — settings access failures degrade to "disabled".
	"""
	try:
		val = frappe.db.get_single_value("IDP Settings", "undo_window_minutes")
	except Exception:
		return 5
	if val is None or val == "":
		return 5
	try:
		return max(0, int(val))
	except (TypeError, ValueError):
		return 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_system_manager(user: str | None = None) -> bool:
	user = user or frappe.session.user
	try:
		return "System Manager" in (frappe.get_roles(user) or [])
	except Exception:
		return False


def _load_message(message_id: str) -> "frappe.Document":
	"""Return the IDP Message, throwing a friendly error on failure."""
	if not message_id:
		frappe.throw(_("message_id is required"), frappe.ValidationError)
	try:
		return frappe.get_doc("IDP Message", message_id)
	except frappe.DoesNotExistError:
		frappe.throw(_("Confirmation message not found"), frappe.DoesNotExistError)


def _authorise(message: "frappe.Document") -> None:
	"""Reject callers that did not originate the conversation."""
	if _is_system_manager():
		return
	current = frappe.session.user
	conversation = frappe.get_doc("IDP Conversation", message.conversation)
	if conversation.owner != current:
		frappe.throw(
			_("Only the user who confirmed this card can undo it."),
			frappe.PermissionError,
		)


def _check_window(message: "frappe.Document") -> None:
	"""Reject calls that arrive after :attr:`undo_deadline`."""
	deadline = message.get("undo_deadline")
	if not deadline:
		frappe.throw(
			_("This action is not eligible for undo."),
			frappe.ValidationError,
		)
	now = frappe.utils.now_datetime()
	deadline_dt = frappe.utils.get_datetime(deadline)
	if now > deadline_dt:
		frappe.throw(
			_("Undo window has expired."),
			frappe.ValidationError,
		)


def _check_already_undone(message: "frappe.Document") -> None:
	"""Treat re-clicks as a friendly no-op rather than a hard failure.

	The card payload carries ``card.undone = True`` after a successful
	undo so the second click reports the prior outcome instead of
	chasing a now-missing ERPNext document.
	"""
	import json

	payload = message.rendered_card_payload
	if not payload:
		return
	try:
		card = json.loads(payload)
	except (TypeError, ValueError):
		return
	if isinstance(card, dict) and card.get("undone"):
		frappe.throw(
			_("This document has already been undone."),
			frappe.ValidationError,
		)


# ---------------------------------------------------------------------------
# Reversal primitives
# ---------------------------------------------------------------------------


def _reverse_doc(doctype: str, docname: str) -> dict:
	"""Roll back *doctype/docname* respecting its current docstatus.

	Returns a dict describing what happened so the API response can
	surface a concrete reason ("deleted", "cancelled") to the caller.

	The Frappe permission system is the source of truth here — we
	deliberately leave ``ignore_permissions`` alone so a user without
	``delete`` / ``cancel`` rights on the underlying DocType gets a
	clean ``frappe.PermissionError`` from the framework.
	"""
	if not frappe.db.exists(doctype, docname):
		return {"action": "noop", "reason": "document_not_found"}

	doc = frappe.get_doc(doctype, docname)
	docstatus = int(getattr(doc, "docstatus", 0) or 0)

	# Draft → straight delete.
	if docstatus == _DRAFT:
		doc.delete()
		return {"action": "deleted", "docstatus": _DRAFT}

	# Submitted → cancel if the DocType is submittable.
	if docstatus == _SUBMITTED:
		is_submittable = bool(
			frappe.db.get_value("DocType", doctype, "is_submittable")
		)
		if not is_submittable:
			frappe.throw(
				_("{0} is not submittable; nothing to undo.").format(doctype),
				frappe.ValidationError,
			)
		try:
			doc.cancel()
		except frappe.LinkExistsError as exc:
			frappe.throw(
				_(
					"Cannot undo: {0} {1} is referenced by another document "
					"({2}). Cancel the dependent record first."
				).format(doctype, docname, str(exc)),
				frappe.ValidationError,
			)
		return {"action": "cancelled", "docstatus": _CANCELLED}

	# Already cancelled — nothing to do.
	return {"action": "noop", "reason": "already_cancelled", "docstatus": docstatus}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def undo_confirmation(message_id: str) -> dict:
	"""Reverse the ERPNext document created from *message_id*.

	Returns ``{message_id, doctype, docname, action, reason}``.  The
	caller is the chatbot frontend: it disables the undo banner and
	replaces it with an "Undone" pill on success.
	"""

	window_min = get_undo_window_minutes()
	if window_min <= 0:
		frappe.throw(
			_("Undo is disabled by the administrator."),
			frappe.ValidationError,
		)

	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)

	message = _load_message(message_id)
	_check_already_undone(message)
	_authorise(message)
	_check_window(message)

	doctype = message.get("created_doctype")
	docname = message.get("created_docname")
	if not doctype or not docname:
		frappe.throw(
			_("This message did not create an ERPNext document."),
			frappe.ValidationError,
		)

	try:
		result = _reverse_doc(doctype, docname)
	except frappe.PermissionError:
		raise
	except frappe.ValidationError:
		raise
	except Exception as exc:  # noqa: BLE001 — surface to user via envelope
		logger.exception(
			"undo_confirmation failed message=%s %s/%s: %s",
			message.name,
			doctype,
			docname,
			exc,
		)
		frappe.throw(
			_("Undo failed: {0}").format(str(exc) or exc.__class__.__name__),
			frappe.ValidationError,
		)

	# Stamp the card so subsequent reads (and re-renders) lock the
	# banner.  We never clear ``created_doctype`` / ``created_docname``
	# — keeping them lets the audit trail remain inspectable even
	# after the underlying document is gone.
	import json

	payload = message.rendered_card_payload
	card = None
	if payload:
		try:
			card = json.loads(payload)
		except (TypeError, ValueError):
			card = None
	if isinstance(card, dict):
		card["undone"] = True
		card["undo_result"] = {
			"action": result.get("action"),
			"doctype": doctype,
			"docname": docname,
		}
		# Closing the window also kills the action buttons (already
		# locked at confirm time, but defensive).
		card["actions"] = []
		message.rendered_card_payload = json.dumps(card, default=str)
		message.save(ignore_permissions=False)
		frappe.db.commit()

	# Audit trail — reuses the IDP Document Log table so the undo is
	# captured alongside the original creation.
	try:
		log_event(
			file_url=f"<undo:{doctype}>",
			file_name=docname,
			target_doctype=doctype,
			status="Failed" if result.get("action") == "noop" else "Created",
			created_doctype=doctype,
			created_document=docname,
			error_message=(
				f"undo:{result.get('action')}"
				+ (f":{result.get('reason')}" if result.get("reason") else "")
			),
			user=user,
		)
	except Exception:  # noqa: BLE001 — audit must never break the request
		logger.debug("undo audit log skipped", exc_info=False)

	# Post a short assistant message so the chat surface reflects the
	# reversal.  Mirrors the ack pattern used in ``confirm_card``.
	try:
		ack = frappe.new_doc("IDP Message")
		ack.conversation = message.conversation
		ack.role = "assistant"
		if result.get("action") == "deleted":
			ack.content = _("{0} {1} was undone (draft deleted).").format(
				doctype, docname
			)
		elif result.get("action") == "cancelled":
			ack.content = _("{0} {1} was undone (cancelled).").format(
				doctype, docname
			)
		else:
			ack.content = _("Nothing to undo for {0} {1}.").format(doctype, docname)
		ack.rendered_card_type = "InfoCard"
		ack.rendered_card_payload = json.dumps(
			{
				"card_type": "InfoCard",
				"title": _("Undone"),
				"body": ack.content,
			},
			default=str,
		)
		ack.insert(ignore_permissions=True)
		try:
			frappe.publish_realtime(
				event="idp_conversation_message",
				message={"conversation": message.conversation, "message": ack.as_dict()},
				doctype="IDP Conversation",
				docname=message.conversation,
			)
		except Exception:
			logger.debug("realtime publish skipped for undo ack", exc_info=False)
	except Exception:  # noqa: BLE001
		logger.debug("undo ack message skipped", exc_info=False)

	logger.info(
		"undo_confirmation user=%s message=%s %s/%s -> %s",
		user,
		message.name,
		doctype,
		docname,
		result.get("action"),
	)

	return {
		"message_id": message.name,
		"doctype": doctype,
		"docname": docname,
		"action": result.get("action"),
		"reason": result.get("reason"),
	}


@frappe.whitelist()
def undo_deletion(undo_token: str) -> dict:
	"""Restore a document deleted via ``delete_document``.

	*undo_token* is the IDP Document Log row name returned by the tool
	(``data.undo_token``).  The audit row carries the pre-delete
	snapshot; we re-insert it iff (a) the original deleter or a
	``System Manager`` is calling, (b) the row's ``creation`` is still
	within the configured undo window, and (c) the doc does not already
	exist (idempotency — a re-click is a no-op).
	"""
	import json as _json

	if not undo_token:
		frappe.throw(_("undo_token is required"), frappe.ValidationError)

	window_min = get_undo_window_minutes()
	if window_min <= 0:
		frappe.throw(
			_("Undo is disabled by the administrator."),
			frappe.ValidationError,
		)

	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)

	try:
		log = frappe.get_doc("IDP Document Log", undo_token)
	except frappe.DoesNotExistError:
		frappe.throw(_("Undo token not found."), frappe.DoesNotExistError)

	if log.status != "Deleted":
		frappe.throw(
			_("This token does not correspond to a deletion."),
			frappe.ValidationError,
		)

	# Authorisation: original deleter or System Manager.
	if log.user and log.user != user and not _is_system_manager(user):
		frappe.throw(
			_("Only the user who deleted this record can undo it."),
			frappe.PermissionError,
		)

	# Window check based on the audit row's creation timestamp.
	from datetime import timedelta

	now = frappe.utils.now_datetime()
	created = frappe.utils.get_datetime(log.creation)
	if (now - created) > timedelta(minutes=window_min):
		frappe.throw(_("Undo window has expired."), frappe.ValidationError)

	doctype = log.created_doctype
	docname = log.created_document
	if not doctype or not docname:
		frappe.throw(
			_("Audit row does not reference a deleted document."),
			frappe.ValidationError,
		)

	# Idempotency — re-click is a no-op.
	if frappe.db.exists(doctype, docname):
		return {
			"undo_token": undo_token,
			"doctype": doctype,
			"docname": docname,
			"action": "noop",
			"reason": "already_restored",
		}

	# Pull the snapshot out of the audit row.
	payload_raw = log.extraction_data or "{}"
	try:
		payload = _json.loads(payload_raw) if isinstance(payload_raw, str) else (payload_raw or {})
	except (TypeError, ValueError):
		payload = {}
	snapshot = (payload or {}).get("snapshot") or {}
	if not isinstance(snapshot, dict) or not snapshot:
		frappe.throw(
			_("Deleted record snapshot is missing or unreadable."),
			frappe.ValidationError,
		)
	snapshot["doctype"] = doctype
	snapshot["name"] = docname

	try:
		new_doc = frappe.get_doc(snapshot)
		new_doc.insert()
	except frappe.PermissionError:
		raise
	except Exception as exc:
		logger.exception(
			"undo_deletion failed token=%s %s/%s: %s",
			undo_token,
			doctype,
			docname,
			exc,
		)
		frappe.throw(
			_("Restore failed: {0}").format(str(exc) or exc.__class__.__name__),
			frappe.ValidationError,
		)

	frappe.db.commit()
	logger.info(
		"undo_deletion user=%s token=%s %s/%s restored",
		user,
		undo_token,
		doctype,
		docname,
	)
	return {
		"undo_token": undo_token,
		"doctype": doctype,
		"docname": docname,
		"action": "restored",
	}


__all__ = ["undo_confirmation", "undo_deletion", "get_undo_window_minutes"]
