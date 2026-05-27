# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Settings retrieval API endpoint.

Returns IDP configuration for the frontend: supported formats,
DocTypes, OCR languages, feature flags, and file size limits.
"""

import frappe

from idp.core.config import get_idp_settings, is_feature_enabled
from idp.core.constants import (
	MAX_FILE_SIZE_MB,
	OCR_LANGUAGES,
	SUPPORTED_DOCTYPES,
	SUPPORTED_MIME_TYPES,
)
from idp.core.logger import get_logger

logger = get_logger("idp.api.settings")


@frappe.whitelist()
def get_settings() -> dict:
	"""Return IDP settings for the frontend.

	Returns:
		dict with keys:
			- ``enabled``: bool — whether IDP is globally enabled
			- ``supported_formats``: list of supported file extensions
			- ``supported_mime_types``: list of accepted MIME types
			- ``supported_doctypes``: list of target DocTypes
			- ``ocr_languages``: dict of ``{code: name}``
			- ``max_file_size_mb``: int
			- ``default_ocr_language``: str
			- ``features``: dict of feature flags
	"""
	settings = get_idp_settings()

	# Build supported extensions from MIME map
	from idp.core.constants import EXTENSION_TO_MIME

	supported_extensions = sorted(EXTENSION_TO_MIME.keys())

	return {
		"enabled": bool(settings.get("enabled", True)),
		"supported_formats": supported_extensions,
		"supported_mime_types": sorted(SUPPORTED_MIME_TYPES.keys()),
		"supported_doctypes": SUPPORTED_DOCTYPES,
		"ocr_languages": OCR_LANGUAGES,
		"max_file_size_mb": settings.get("max_file_size_mb", MAX_FILE_SIZE_MB),
		"default_ocr_language": settings.get("default_ocr_language", "en"),
		"features": {
			"ocr": is_feature_enabled("enable_ocr"),
			"table_extraction": is_feature_enabled("enable_table_extraction"),
			"comparison": is_feature_enabled("enable_comparison"),
			"auto_create_masters": is_feature_enabled("auto_create_missing_masters"),
			"write_operations": is_feature_enabled("enable_write_operations"),
		},
		# Phase 29 — confidence dot toggle exposed at the top level so
		# the chat surface can read it without a second roundtrip.
		"show_confidence_dots": settings.get("show_confidence_dots", 1),
		# Phase 31 — UX polish feature flags.
		"enable_cost_footer": settings.get("enable_cost_footer", 1),
		"enable_preflight_warning": settings.get("enable_preflight_warning", 1),
		"enable_suggested_prompts": settings.get("enable_suggested_prompts", 1),
		"enable_sidebar_search": settings.get("enable_sidebar_search", 1),
		"enable_bulk_actions": settings.get("enable_bulk_actions", 1),
		"enable_conversation_delete": settings.get("enable_conversation_delete", 1),
	}
