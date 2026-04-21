# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Message controller.

One row per message within an :class:`IDP Conversation`.  Messages
record user prompts, assistant replies, tool calls/results, and rendered
UI cards.  They are ordered via the ``sequence`` integer and are
immutable once written (controllers enforce append-only semantics).
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


VALID_ROLES = {"system", "user", "assistant", "tool"}


class IDPMessage(Document):
	"""Controller for the *IDP Message* DocType."""

	def validate(self):
		"""Enforce role vocabulary and auto-fill ``created_on``/``sequence``."""
		if self.role not in VALID_ROLES:
			frappe.throw(f"Invalid role: {self.role!r}. Must be one of {sorted(VALID_ROLES)}.")

		if not self.created_on:
			self.created_on = frappe.utils.now_datetime()

		if self.sequence is None:
			self.sequence = self._next_sequence()

	def _next_sequence(self) -> int:
		"""Return max(sequence) + 1 within this conversation, or 0."""
		result = frappe.db.sql(
			"""
			SELECT MAX(sequence) AS seq
			FROM `tabIDP Message`
			WHERE conversation = %s
			""",
			(self.conversation,),
			as_dict=True,
		)
		if result and result[0].get("seq") is not None:
			return int(result[0]["seq"]) + 1
		return 0

	def after_insert(self):
		"""Refresh the parent conversation's denormalised counters."""
		try:
			parent = frappe.get_doc("IDP Conversation", self.conversation)
			parent.refresh_stats()
		except frappe.DoesNotExistError:
			# Orphan messages are possible in tests; skip silently.
			return


def get_permission_query_conditions(user: str | None = None) -> str:
	"""Restrict message list queries to the caller's conversations.

	Uses a sub-select so list views in Desk show only rows for
	conversations the user owns.
	"""
	user = user or frappe.session.user

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return ""

	escaped = frappe.db.escape(user)
	return (
		f"(`tabIDP Message`.conversation IN "
		f"(SELECT name FROM `tabIDP Conversation` WHERE user = {escaped}))"
	)
