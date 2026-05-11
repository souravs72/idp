# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Record creation API endpoints.

Provides endpoints to create ERPNext documents from extracted data
and to check for missing master records before creation.
"""

import json

import frappe

from idp.core.audit import log_creation_event
from idp.core.config import get_default_company
from idp.core.constants import SUPPORTED_DOCTYPES
from idp.core.exceptions import IDPError, MissingMasterError, ValidationError
from idp.core.logger import get_logger
from idp.mappers import MappedDocument, create_document
from idp.mappers.document_creator import _find_missing_masters

logger = get_logger("idp.api.create")


def _parse_json_param(value: str | dict | list, param_name: str) -> dict | list:
	"""Parse a JSON string parameter, or return as-is if already parsed."""
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (json.JSONDecodeError, TypeError) as exc:
		frappe.throw(f"Invalid JSON for {param_name}: {exc}", frappe.ValidationError)


@frappe.whitelist()
def create_erp_document(
	target_doctype: str,
	extracted_data: str | dict,
	company: str | None = None,
	create_missing_masters: bool = False,
	item_defaults: str | dict | None = None,
) -> dict:
	"""Create an ERPNext document from extracted and user-reviewed data.

	Called after the user has reviewed and optionally edited the extraction
	results from :func:`idp.api.extract.extract_document`.

	Args:
		target_doctype: ERPNext DocType (e.g. ``Purchase Invoice``).
		extracted_data: JSON string or dict with ``{header: {...}, items: [...]}``.
		company: Company to assign. Falls back to ``get_default_company()``.
		create_missing_masters: When True, auto-create Supplier/Customer/Item
			records if they don't exist.
		item_defaults: JSON string or dict with default values for auto-created
			Items (e.g. ``{"is_stock_item": 1, "item_group": "Products"}``).

	Returns:
		dict with keys:
			- ``success``: bool
			- ``doctype``: str
			- ``name``: str (document name)
			- ``url``: str (Frappe desk URL)
			- ``warnings``: list[str]
			- ``created_masters``: list[dict]

		On failure:
			- ``success``: False
			- ``error``: str
			- ``error_type``: str (exception class name)
			- ``details``: dict
	"""
	company = company or get_default_company()

	# Frappe sends checkbox values as strings from the frontend
	if isinstance(create_missing_masters, str):
		create_missing_masters = create_missing_masters.lower() in ("true", "1", "yes")

	# --- Input validation ---
	if target_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			f'Unsupported DocType: "{target_doctype}". Supported: {", ".join(SUPPORTED_DOCTYPES)}',
			frappe.ValidationError,
		)

	data = _parse_json_param(extracted_data, "extracted_data")
	if not isinstance(data, dict):
		frappe.throw(
			"extracted_data must be a JSON object with 'header' and 'items' keys.", frappe.ValidationError
		)

	item_defs = None
	if item_defaults:
		item_defs = _parse_json_param(item_defaults, "item_defaults")
		if not isinstance(item_defs, dict):
			frappe.throw("item_defaults must be a JSON object.", frappe.ValidationError)

	# --- Build MappedDocument ---
	mapped = MappedDocument(
		doctype=target_doctype,
		header=data.get("header", {}),
		items=data.get("items", []),
	)

	try:
		result = create_document(
			mapped,
			company=company,
			create_missing_masters=create_missing_masters,
			item_defaults=item_defs,
		)
		logger.info(f"Created {result['doctype']} {result['name']} via API")
		log_creation_event(
			target_doctype=target_doctype,
			success=True,
			created_name=result.get("name"),
			company=company,
			warnings=result.get("warnings") or [],
		)
		return result

	except ValidationError as exc:
		logger.warning(f"Validation failed during create: {exc}")
		log_creation_event(
			target_doctype=target_doctype,
			success=False,
			company=company,
			error_message=f"ValidationError: {exc}",
		)
		return {
			"success": False,
			"error": str(exc),
			"error_type": "ValidationError",
			"details": exc.details,
		}

	except MissingMasterError as exc:
		logger.info(f"Missing masters during create: {exc}")
		log_creation_event(
			target_doctype=target_doctype,
			success=False,
			company=company,
			error_message=f"MissingMasterError: {exc}",
		)
		return {
			"success": False,
			"error": str(exc),
			"error_type": "MissingMasterError",
			"details": exc.details,
		}

	except IDPError as exc:
		logger.warning(f"IDP error during create: {exc}")
		log_creation_event(
			target_doctype=target_doctype,
			success=False,
			company=company,
			error_message=f"{type(exc).__name__}: {exc}",
		)
		return {
			"success": False,
			"error": str(exc),
			"error_type": type(exc).__name__,
			"details": exc.details,
		}

	except Exception as exc:
		logger.error(f"Unexpected error during create: {exc}")
		log_creation_event(
			target_doctype=target_doctype,
			success=False,
			company=company,
			error_message=f"Unexpected: {exc}",
		)
		frappe.throw(
			f"Document creation failed: {exc}",
			title="IDP Creation Error",
		)


@frappe.whitelist()
def get_missing_masters(
	target_doctype: str,
	extracted_data: str | dict,
	company: str | None = None,
) -> dict:
	"""Check what master records are missing before document creation.

	Useful for the frontend to show a "missing masters" dialog and let
	the user decide whether to auto-create them.

	Args:
		target_doctype: ERPNext DocType (e.g. ``Purchase Invoice``).
		extracted_data: JSON string or dict with ``{header: {...}, items: [...]}``.
		company: Company context.

	Returns:
		dict with keys:
			- ``missing``: list of ``{doctype, value, fieldname}``
			- ``count``: int
	"""
	company = company or get_default_company()

	if target_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(
			f'Unsupported DocType: "{target_doctype}".',
			frappe.ValidationError,
		)

	data = _parse_json_param(extracted_data, "extracted_data")
	if not isinstance(data, dict):
		frappe.throw("extracted_data must be a JSON object.", frappe.ValidationError)

	mapped = MappedDocument(
		doctype=target_doctype,
		header=data.get("header", {}),
		items=data.get("items", []),
	)

	missing = _find_missing_masters(mapped, company)

	return {
		"missing": missing,
		"count": len(missing),
	}
