# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Document creator — builds Draft ERPNext records from mapped extraction data.

Validates, resolves missing masters, builds the ``frappe.get_doc()`` dict,
inserts as Draft, and preserves text fields that ERPNext hooks may overwrite.
"""

import frappe

from idp.core.config import get_default_company
from idp.core.exceptions import MappingError, MissingMasterError, ValidationError
from idp.core.logger import get_logger
from idp.idp.mappers.base import MappedDocument, get_doctype_schema
from idp.idp.validators.business_rules import validate_business_rules
from idp.idp.validators.schema_validator import validate_schema

logger = get_logger("idp.document_creator")

# ---------------------------------------------------------------------------
# Default item settings for auto-created Items
# ---------------------------------------------------------------------------

_DEFAULT_ITEM_SETTINGS: dict = {
	"is_stock_item": 0,
	"is_fixed_asset": 0,
	"item_group": "All Item Groups",
	"stock_uom": "Nos",
}

# Text fields that ERPNext hooks may clear on insert
_TEXT_FIELDS_TO_PRESERVE: list[str] = [
	"terms",
	"remarks",
	"remark",
	"notes",
	"instructions",
	"description",
]


# ===========================================================================
# Public API
# ===========================================================================


def create_document(
	mapped_data: MappedDocument,
	company: str = "",
	create_missing_masters: bool = False,
	item_defaults: dict | None = None,
	item_overrides: dict | None = None,
	skip_validation: bool = False,
) -> dict:
	"""Create an ERPNext document (as Draft) from mapped extraction data.

	Args:
		mapped_data: The validated ``MappedDocument`` from the mapping pipeline.
		company: Company to assign. Falls back to ``get_default_company()``.
		create_missing_masters: When True, auto-create Supplier/Customer/Item
			records if they don't exist.
		item_defaults: Override defaults for auto-created Items, e.g.
			``{"is_stock_item": 1, "item_group": "Products"}``.
		item_overrides: Per-item-code overrides, keyed by the item_code that
			will be auto-created. Each value is a dict of Item field
			overrides (``is_stock_item``, ``item_name``, ``description``,
			``stock_uom``) — these win over ``item_defaults``.
		skip_validation: When True, skip schema + business-rule validation
			before creating the document.  Useful when the caller has already
			validated separately.

	Returns:
		dict with keys:
			- ``success``: bool
			- ``doctype``: str
			- ``name``: str (name of the created document)
			- ``url``: str (Frappe desk URL)
			- ``warnings``: list[str]
			- ``created_masters``: list[dict] (auto-created master records)

	Raises:
		ValidationError: If validation fails and ``skip_validation`` is False.
		MissingMasterError: If masters are missing and ``create_missing_masters``
			is False.
		MappingError: If document insertion fails.
	"""
	company = company or get_default_company()
	warnings: list[str] = []
	created_masters: list[dict] = []

	# ------------------------------------------------------------------
	# 1. Validate
	# ------------------------------------------------------------------
	if not skip_validation:
		schema_result = validate_schema(mapped_data)
		if not schema_result.is_valid:
			error_msgs = [f"{e.field}: {e.message}" for e in schema_result.errors]
			raise ValidationError(
				f"Schema validation failed with {len(schema_result.errors)} error(s)",
				details={"errors": error_msgs},
			)
		# Business rules produce warnings, not hard errors
		biz_issues = validate_business_rules(mapped_data, company)
		if biz_issues:
			warnings.extend(biz_issues)

	# ------------------------------------------------------------------
	# 2. Check for missing masters
	# ------------------------------------------------------------------
	missing = _find_missing_masters(mapped_data, company)
	if missing:
		if create_missing_masters:
			result = auto_create_missing_masters(missing, company, item_defaults, item_overrides)
			created_masters = result["created"]
			for fail in result["failed"]:
				warnings.append(f'Failed to create {fail["doctype"]} "{fail["name"]}": {fail["error"]}')
			# Re-check: any still missing?
			still_missing = _find_missing_masters(mapped_data, company)
			if still_missing:
				names = [f"{m['doctype']}:{m['value']}" for m in still_missing]
				raise MissingMasterError(
					f"Could not create {len(still_missing)} master record(s)",
					details={"missing": names},
				)
		else:
			names = [f"{m['doctype']}:{m['value']}" for m in missing]
			raise MissingMasterError(
				f"{len(missing)} missing master record(s) — set create_missing_masters=True to auto-create",
				details={"missing": names},
			)

	# ------------------------------------------------------------------
	# 3. Build the document dict
	# ------------------------------------------------------------------
	doc_dict = _build_doc_dict(mapped_data, company)

	# ------------------------------------------------------------------
	# 4. Insert as Draft
	# ------------------------------------------------------------------
	try:
		doc = frappe.get_doc(doc_dict)
		doc.flags.ignore_permissions = True
		doc.insert()
	except Exception as exc:
		raise MappingError(
			f"Failed to insert {mapped_data.doctype}: {exc}",
			details={"doctype": mapped_data.doctype, "error": str(exc)},
		)

	# ------------------------------------------------------------------
	# 5. Preserve text fields that hooks may have cleared
	# ------------------------------------------------------------------
	_preserve_text_fields(doc, mapped_data)

	# ------------------------------------------------------------------
	# 6. Return result
	# ------------------------------------------------------------------
	url = frappe.utils.get_url_to_form(doc.doctype, doc.name)
	logger.info(f"Created {doc.doctype} {doc.name} | url={url}")

	return {
		"success": True,
		"doctype": doc.doctype,
		"name": doc.name,
		"url": url,
		"warnings": warnings,
		"created_masters": created_masters,
	}


# ===========================================================================
# Auto-create missing masters
# ===========================================================================


def auto_create_missing_masters(
	missing: list[dict],
	company: str,
	item_defaults: dict | None = None,
	item_overrides: dict | None = None,
) -> dict:
	"""Create minimal master records for missing parties and items.

	Each entry in *missing* is ``{"doctype": "Supplier", "value": "Tara Tech",
	"fieldname": "supplier"}``.

	Creates:
		- **Supplier**: supplier_name, supplier_group, supplier_type
		- **Customer**: customer_name, customer_group, customer_type
		- **Item**: item_name, item_group, is_stock_item, stock_uom
		- **UOM**: uom_name

	``item_overrides`` maps an item_code → field overrides dict that wins
	over ``item_defaults`` for that specific Item (Phase 24).

	Returns:
		``{"created": [{"doctype", "name"}], "failed": [{"doctype", "name", "error"}]}``
	"""
	created: list[dict] = []
	failed: list[dict] = []
	item_settings = {**_DEFAULT_ITEM_SETTINGS, **(item_defaults or {})}
	overrides_by_code = item_overrides or {}

	for entry in missing:
		dt = entry["doctype"]
		value = entry["value"]

		try:
			if dt == "Supplier":
				_create_supplier(value, company)
			elif dt == "Customer":
				_create_customer(value, company)
			elif dt == "Item":
				row_override = overrides_by_code.get(str(value)) or {}
				settings_for_row = {**item_settings, **row_override}
				_create_item(value, company, settings_for_row)
			elif dt == "UOM":
				_create_uom(value)
			else:
				failed.append({"doctype": dt, "name": value, "error": f"Unsupported master type: {dt}"})
				continue

			created.append({"doctype": dt, "name": value})
			logger.info(f"Auto-created {dt}: {value}")
		except Exception as exc:
			failed.append({"doctype": dt, "name": value, "error": str(exc)})
			logger.warning(f"Failed to auto-create {dt} '{value}': {exc}")

	return {"created": created, "failed": failed}


# ===========================================================================
# Text field preservation
# ===========================================================================


def _preserve_text_fields(doc, mapped_data: MappedDocument) -> None:
	"""Re-apply terms, remarks, and other text fields after ``doc.insert()``.

	ERPNext hooks may clear ``terms`` (if no ``tc_name`` match) and ``remarks``
	(auto-generated).  Re-set these from extraction data and save silently.
	"""
	needs_save = False
	header = mapped_data.header

	for field_name in _TEXT_FIELDS_TO_PRESERVE:
		extracted_value = header.get(field_name)
		if not extracted_value:
			continue
		current_value = doc.get(field_name)
		if current_value != extracted_value:
			doc.set(field_name, extracted_value)
			needs_save = True

	if needs_save:
		try:
			doc.flags.ignore_permissions = True
			doc.save()
			logger.info(f"Preserved text fields on {doc.doctype} {doc.name}")
		except Exception as exc:
			logger.warning(f"Could not preserve text fields on {doc.doctype} {doc.name}: {exc}")


# ===========================================================================
# Private helpers
# ===========================================================================


def _find_missing_masters(mapped_data: MappedDocument, company: str) -> list[dict]:
	"""Identify Link fields whose values don't exist in the database."""
	missing: list[dict] = []
	schema = get_doctype_schema(mapped_data.doctype)

	for f in schema["fields"]:
		if f["fieldtype"] != "Link":
			continue
		fieldname = f["fieldname"]
		value = mapped_data.header.get(fieldname)
		if not value:
			continue

		link_doctype = f["options"]
		if not link_doctype:
			continue

		# Only check master-data DocTypes that we can auto-create
		if link_doctype not in ("Supplier", "Customer", "Item", "UOM"):
			continue

		if not frappe.db.exists(link_doctype, str(value)):
			missing.append({"doctype": link_doctype, "value": str(value), "fieldname": fieldname})

	# Also check item-level links (item_code → Item, uom → UOM)
	for row in mapped_data.items:
		item_code = row.get("item_code")
		if item_code and not frappe.db.exists("Item", str(item_code)):
			# Avoid duplicates
			if not any(m["doctype"] == "Item" and m["value"] == str(item_code) for m in missing):
				missing.append({"doctype": "Item", "value": str(item_code), "fieldname": "item_code"})

		uom = row.get("uom")
		if uom and not frappe.db.exists("UOM", str(uom)):
			if not any(m["doctype"] == "UOM" and m["value"] == str(uom) for m in missing):
				missing.append({"doctype": "UOM", "value": str(uom), "fieldname": "uom"})

	return missing


def _build_doc_dict(mapped_data: MappedDocument, company: str) -> dict:
	"""Build the dict suitable for ``frappe.get_doc()``."""
	schema = get_doctype_schema(mapped_data.doctype)

	doc_dict: dict = {
		"doctype": mapped_data.doctype,
	}

	# --- Header fields ---
	valid_fieldnames = {f["fieldname"] for f in schema["fields"]}
	for fieldname, value in mapped_data.header.items():
		if fieldname in valid_fieldnames:
			doc_dict[fieldname] = value

	# Set company if the DocType has a company field and it's not already set
	if "company" not in doc_dict:
		meta = frappe.get_meta(mapped_data.doctype)
		if meta.has_field("company") and company:
			doc_dict["company"] = company

	# --- Child table items ---
	if mapped_data.items:
		child_table_field = _get_primary_child_fieldname(schema)
		if child_table_field:
			child_dt = schema["child_tables"][child_table_field]["doctype"]
			child_valid = {f["fieldname"] for f in schema["child_tables"][child_table_field]["fields"]}

			rows: list[dict] = []
			for row_data in mapped_data.items:
				row = {"doctype": child_dt}
				for fieldname, value in row_data.items():
					if fieldname in child_valid:
						row[fieldname] = value
				rows.append(row)

			doc_dict[child_table_field] = rows

	# --- Child table taxes (Phase 24) ---
	# ERPNext computes ``tax_amount`` from net_total × rate when
	# ``charge_type='On Net Total'``, so the row only needs
	# ``account_head``, ``charge_type``, ``rate`` and ``description``.
	# We still forward ``tax_amount`` when provided so deviations from
	# the recomputed value are auditable in the warnings.
	if mapped_data.taxes and "taxes" in schema.get("child_tables", {}):
		tax_child_dt = schema["child_tables"]["taxes"]["doctype"]
		tax_valid = {f["fieldname"] for f in schema["child_tables"]["taxes"]["fields"]}
		tax_rows: list[dict] = []
		for tax_data in mapped_data.taxes:
			if not isinstance(tax_data, dict):
				continue
			row = {"doctype": tax_child_dt}
			# Default charge_type so ERPNext can compute the tax amount
			# from the net total; the card always sets "On Net Total"
			# but rule-based callers may omit it.
			if "charge_type" in tax_valid:
				row["charge_type"] = tax_data.get("charge_type") or "On Net Total"
			for fieldname, value in tax_data.items():
				if fieldname in tax_valid and value not in (None, ""):
					row[fieldname] = value
			# Skip rows with no account_head — ERPNext will reject them
			# anyway and we'd rather surface that as a warning upstream.
			if not row.get("account_head"):
				continue
			tax_rows.append(row)
		if tax_rows:
			doc_dict["taxes"] = tax_rows

	return doc_dict


def _get_primary_child_fieldname(schema: dict) -> str | None:
	"""Return the fieldname of the primary child table (usually ``items``)."""
	ct = schema.get("child_tables", {})
	if "items" in ct:
		return "items"
	for key in ct:
		return key
	return None


# ---------------------------------------------------------------------------
# Master record creators
# ---------------------------------------------------------------------------


def _create_supplier(name: str, company: str) -> None:
	"""Create a minimal Supplier record."""
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": _get_first_or_default("Supplier Group", "All Supplier Groups"),
			"supplier_type": "Company",
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert()


def _create_customer(name: str, company: str) -> None:
	"""Create a minimal Customer record."""
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_group": _get_first_or_default("Customer Group", "All Customer Groups"),
			"customer_type": "Company",
		}
	)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert()


def _create_item(name: str, company: str, settings: dict) -> None:
	"""Create a minimal Item record.

	``settings`` may carry per-row overrides — ``item_name``,
	``description``, ``stock_uom``, ``is_stock_item`` — so that
	auto-created Items reflect the user's confirmation-card choices
	(Phase 24).
	"""
	uom = settings.get("stock_uom") or "Nos"
	# Ensure the UOM exists
	if not frappe.db.exists("UOM", uom):
		_create_uom(uom)

	doc_dict: dict = {
		"doctype": "Item",
		"item_name": settings.get("item_name") or name,
		"item_code": name,
		"item_group": _get_first_or_default("Item Group", settings.get("item_group", "All Item Groups")),
		"stock_uom": uom,
		"is_stock_item": 1 if settings.get("is_stock_item") else 0,
		"is_fixed_asset": 1 if settings.get("is_fixed_asset") else 0,
	}
	if settings.get("description"):
		doc_dict["description"] = settings["description"]

	doc = frappe.get_doc(doc_dict)
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert()


def _create_uom(name: str) -> None:
	"""Create a UOM record if it doesn't exist."""
	if frappe.db.exists("UOM", name):
		return
	doc = frappe.get_doc(
		{
			"doctype": "UOM",
			"uom_name": name,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()


def _get_first_or_default(doctype: str, default: str) -> str:
	"""Return *default* if it exists, otherwise the first record of *doctype*."""
	if frappe.db.exists(doctype, default):
		return default
	first = frappe.get_all(doctype, pluck="name", limit=1)
	return first[0] if first else default
