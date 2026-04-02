# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Centralised settings reader for the IDP module.

Reads configuration from the *IDP Settings* Single DocType (created in
Phase 11).  Until that DocType exists, every helper returns a sensible
default so the rest of the codebase can import freely without errors.
"""

import frappe

from idp.core.constants import DEFAULT_CONFIDENCE_THRESHOLD


def get_idp_settings() -> dict:
	"""Read IDP Settings (Single DocType).  Cache per-request.

	Returns a ``dict`` of all settings fields.  If the DocType has not
	been created yet (Phase 11), an empty dict with safe defaults is
	returned instead.
	"""
	try:
		return frappe.get_cached_doc("IDP Settings").as_dict()
	except (frappe.DoesNotExistError, Exception):
		return _default_settings()


def get_default_company() -> str:
	"""Resolve the default company from session or Global Defaults.

	Priority:
	1. ``frappe.defaults.get_user_default("company")``
	2. ``frappe.db.get_single_value("Global Defaults", "default_company")``
	3. Empty string (caller decides how to handle)
	"""
	company = frappe.defaults.get_user_default("company")
	if company:
		return company

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	return company or ""


def is_feature_enabled(feature: str) -> bool:
	"""Check if a feature flag is enabled in IDP Settings.

	Recognised feature names (mapped to IDP Settings field names):
	- ``enable_ocr``
	- ``enable_write_operations``
	- ``enable_comparison``
	- ``enable_table_extraction``
	- ``enable_layout_analysis``
	- ``enable_pdf``, ``enable_images``, ``enable_excel``,
	  ``enable_csv``, ``enable_docx``

	Returns ``True`` by default when the setting does not exist yet.
	"""
	settings = get_idp_settings()
	# When settings DocType is missing we get the defaults dict
	# which has every feature enabled.
	return bool(settings.get(feature, True))


def get_ocr_language() -> str:
	"""Default OCR language from settings, fallback ``'en'``."""
	settings = get_idp_settings()
	return settings.get("default_ocr_language") or "en"


def get_confidence_threshold() -> float:
	"""Minimum OCR confidence (0.0-1.0) before flagging for review.

	Returns the configured threshold or :pydata:`DEFAULT_CONFIDENCE_THRESHOLD`.
	"""
	settings = get_idp_settings()
	threshold = settings.get("confidence_threshold")
	if threshold is not None and threshold > 0:
		return float(threshold)
	return DEFAULT_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _default_settings() -> dict:
	"""Safe defaults used before the IDP Settings DocType is created."""
	return {
		"enabled": 1,
		"default_ocr_language": "en",
		"confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
		"enable_table_extraction": 1,
		"enable_layout_analysis": 1,
		"max_file_size_mb": 25,
		"default_target_doctype": "Purchase Invoice",
		"enable_write_operations": 0,
		"auto_create_missing_masters": 0,
		"enable_comparison": 1,
		"enable_pdf": 1,
		"enable_images": 1,
		"enable_excel": 1,
		"enable_csv": 1,
		"enable_docx": 1,
		"ocr_timeout_seconds": 60,
		"max_pages_per_pdf": 50,
	}
