# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Batch Job controller."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class IDPBatchJob(Document):
	"""Controller for the *IDP Batch Job* DocType."""

	def before_save(self) -> None:
		# Keep counters internally consistent
		items = self.get("items") or []
		self.total_files = len(items)
		self.processed_files = sum(
			1 for it in items if (it.status or "") in ("Success", "Failed", "Needs Review")
		)
		self.succeeded = sum(1 for it in items if it.status == "Success")
		self.failed = sum(1 for it in items if it.status == "Failed")
		self.needs_review = sum(1 for it in items if it.status == "Needs Review")

		if self.processed_files >= self.total_files and self.total_files > 0:
			if self.status == "Running":
				self.status = "Completed"
				if not self.completed_on:
					self.completed_on = frappe.utils.now_datetime()


def get_permission_query_conditions(user: str | None = None) -> str:
	"""Restrict listing to the owner for IDP User role, unrestricted for managers."""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"(`tabIDP Batch Job`.`user` = {frappe.db.escape(user)})"
