# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Extraction Template controller.

User-defined template overriding the default keyword -> fieldname mapping
for specific recurring document formats (Phase 15 groundwork).
"""

import json

import frappe
from frappe.model.document import Document


class IDPExtractionTemplate(Document):
	"""Controller for the *IDP Extraction Template* DocType."""

	def validate(self):
		"""Ensure the JSON fields are well-formed."""
		for fieldname in ("field_mappings", "validation_rules"):
			value = self.get(fieldname)
			if not value:
				continue
			if isinstance(value, str):
				try:
					json.loads(value)
				except json.JSONDecodeError as exc:
					frappe.throw(
						f"{fieldname.replace('_', ' ').title()} is not valid JSON: {exc}"
					)

		# Phase 16 (§TE.5) — per-DocType LLM fallback threshold.
		if self.llm_fallback_threshold is not None:
			if self.llm_fallback_threshold < 0 or self.llm_fallback_threshold > 1:
				frappe.throw("LLM Fallback Threshold must be between 0.0 and 1.0")
