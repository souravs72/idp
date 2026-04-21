# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Document Log controller.

Processing history record for every document ingested through the IDP
pipeline.  One row per upload captures OCR metadata, extraction payload,
validation errors, and the final ERPNext document (if created).
"""

import frappe
from frappe.model.document import Document


class IDPDocumentLog(Document):
	"""Controller for the *IDP Document Log* DocType."""

	def before_insert(self):
		"""Default the *user* field to the session user if not supplied."""
		if not self.user:
			self.user = frappe.session.user
