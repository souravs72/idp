# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Conversation controller.

Parent container for a chatbot-style IDP session.  Stores the ordered
stream of :class:`IDP Message` children, the file alias registry rows
(IDP Conversation Attachment), and usage/cost counters.

The *user* field is the owner-equivalent filter used by
:pyfunc:`get_permission_query_conditions` and the ``has_permission`` hook
registered in ``hooks.py``.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class IDPConversation(Document):
	"""Controller for the *IDP Conversation* DocType."""

	def before_insert(self):
		"""Default ``user`` to the session user; generate a title if empty."""
		if not self.user:
			self.user = frappe.session.user
		if not self.title:
			self.title = f"Conversation — {frappe.utils.now_datetime().strftime('%Y-%m-%d %H:%M')}"
		if not self.status:
			self.status = "Active"
		if self.total_tokens_used is None:
			self.total_tokens_used = 0
		if self.message_count is None:
			self.message_count = 0

	def refresh_stats(self) -> None:
		"""Recompute ``message_count``, ``total_tokens_used``, ``last_message_on``.

		Called after messages are appended to keep the parent row in sync
		for list-view rendering without an expensive join.

		Uses :mod:`frappe.qb` because modern Frappe rejects raw SQL
		aggregate strings (``count(...)``, ``sum(...)``) passed via the
		``fields`` argument of :func:`frappe.get_all`.
		"""
		from frappe.query_builder.functions import Count, Max, Sum

		Message = frappe.qb.DocType("IDP Message")
		row = (
			frappe.qb.from_(Message)
			.select(
				Count(Message.name).as_("count"),
				Max(Message.created_on).as_("last_on"),
				Sum(Message.tokens_in).as_("tokens_in"),
				Sum(Message.tokens_out).as_("tokens_out"),
			)
			.where(Message.conversation == self.name)
		).run(as_dict=True)

		if not row:
			return
		stats = row[0] or {}
		self.message_count = int(stats.get("count") or 0)
		self.last_message_on = stats.get("last_on")
		self.total_tokens_used = int(
			(stats.get("tokens_in") or 0) + (stats.get("tokens_out") or 0)
		)
		self.db_update()

	def add_attachment(
		self,
		*,
		file_url: str,
		file_name: str,
		mime_type: str,
		file_id: str,
		file_size: int | None = None,
		tabfile_name: str | None = None,
		inline_text_preview: str | None = None,
	) -> None:
		"""Append an attachment row, idempotent on ``file_id`` and ``file_url``."""
		for row in self.attachments or []:
			if row.file_id == file_id or row.file_url == file_url:
				return

		self.append(
			"attachments",
			{
				"file_id": file_id,
				"file_name": file_name,
				"file_url": file_url,
				"mime_type": mime_type,
				"file_size": file_size,
				"uploaded_on": frappe.utils.now_datetime(),
				"tabfile_name": tabfile_name,
				"inline_text_preview": (inline_text_preview or "")[:15000],
			},
		)


def get_permission_query_conditions(user: str | None = None) -> str:
	"""Restrict list queries to conversations owned by the caller.

	System Manager and Administrator see every row.  All other users see
	only conversations where ``user = <current_user>``.

	Returns the SQL fragment appended to the ``WHERE`` clause (without
	the leading ``AND``).
	"""
	user = user or frappe.session.user

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return ""

	escaped = frappe.db.escape(user)
	return f"(`tabIDP Conversation`.user = {escaped})"
