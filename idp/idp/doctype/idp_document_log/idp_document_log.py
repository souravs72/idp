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

	def before_save(self):
		"""Compute the Phase 11 \u00a7TE.8 tokens-per-field efficiency metric.

		``tokens_per_extracted_field = llm_tokens_used / |extraction_data|``
		where the denominator is the count of populated extraction fields.
		Read-only on the form; refreshed on every save.
		"""
		tokens = self.llm_tokens_used or 0
		if not tokens:
			self.tokens_per_extracted_field = 0.0
			return

		data = self.extraction_data
		if isinstance(data, str):
			try:
				import json as _json

				data = _json.loads(data) if data else {}
			except ValueError:
				data = {}

		field_count = 0
		if isinstance(data, dict):
			# Count only top-level populated scalar fields; line-item tables
			# inflate the denominator otherwise.
			field_count = sum(1 for v in data.values() if v not in (None, "", [], {}))
		if field_count <= 0:
			self.tokens_per_extracted_field = 0.0
		else:
			self.tokens_per_extracted_field = round(tokens / field_count, 3)
