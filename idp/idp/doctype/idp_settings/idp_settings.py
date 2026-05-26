# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Settings controller.

Single DocType that holds global configuration for the IDP module.
Values are consumed by ``idp.core.config.get_idp_settings``.
"""

import frappe
from frappe.model.document import Document


class IDPSettings(Document):
	"""Controller for the *IDP Settings* single DocType."""

	def validate(self):
		"""Clamp numeric settings to safe ranges before save."""
		if self.confidence_threshold is not None:
			if self.confidence_threshold < 0 or self.confidence_threshold > 1:
				frappe.throw("Confidence threshold must be between 0.0 and 1.0")

		if self.max_file_size_mb is not None and self.max_file_size_mb <= 0:
			frappe.throw("Max File Size (MB) must be greater than zero")

		if self.ocr_timeout_seconds is not None and self.ocr_timeout_seconds <= 0:
			frappe.throw("OCR timeout must be greater than zero")

		if self.max_pages_per_pdf is not None and self.max_pages_per_pdf <= 0:
			frappe.throw("Max pages per PDF must be greater than zero")

		if self.llm_fallback_threshold_default is not None:
			if self.llm_fallback_threshold_default < 0 or self.llm_fallback_threshold_default > 1:
				frappe.throw("LLM fallback threshold must be between 0.0 and 1.0")

		for fname in (
			"active_retention_days",
			"archived_retention_days",
			"auto_purge_failed_after_days",
		):
			val = self.get(fname)
			if val is not None and val < 0:
				frappe.throw(f"{fname} must be \u2265 0")

		# Enforce unique purpose per llm_model_routes row.
		seen_purposes: set[str] = set()
		for row in (self.llm_model_routes or []):
			if not row.purpose:
				continue
			if row.purpose in seen_purposes:
				frappe.throw(f"Duplicate LLM model route for purpose '{row.purpose}'")
			seen_purposes.add(row.purpose)
