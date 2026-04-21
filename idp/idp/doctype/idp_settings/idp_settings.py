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
