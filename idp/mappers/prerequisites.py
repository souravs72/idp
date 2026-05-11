# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Prerequisite detector for the Phase 20 ConfirmationCard.

Walks a :class:`MappedDocument` and reports every Link field whose
target master record does not yet exist.  The result feeds two
slots in the card:

* ``missing_masters`` — rendered as a bulleted list with a "Create
  new" affordance per row.
* per-item / per-tax ``status: New|Existing`` annotations — the
  detector also produces a ``{(doctype, name): exists}`` lookup the
  card builder uses to flag rows.

Targets covered (per roadmap §20.1):

* Header — ``supplier``, ``customer``, ``cost_center``, ``account``,
  ``currency``, ``tax_template``, ``payment_terms_template``,
  ``project``, ``warehouse`` …
* Items — ``item_code``, ``uom``, ``warehouse``, ``expense_account``,
  ``income_account``.
* Taxes — ``account``, ``account_head``, ``cost_center``.

Duplicate ``(doctype, name)`` entries are collapsed so a missing item
referenced from three rows yields a single :class:`MissingMaster`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from idp.core.logger import get_logger
from idp.mappers.base import MappedDocument, get_doctype_schema

logger = get_logger("idp.mappers.prerequisites")


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class MissingMaster:
	"""A master record that needs to be created before insert."""

	doctype: str  # "Supplier", "Customer", "Item", "UOM", "Account"
	name: str  # Proposed name (free text from extraction)
	display_field: str  # e.g. "supplier_name"
	source_field: str  # Parent fieldname that triggered the gap
	source_row: int | None = None  # Child-row index for item-level misses
	suggested_defaults: dict = field(default_factory=dict)
	required_fields: list[str] = field(default_factory=list)

	def to_dict(self) -> dict:
		return {
			"doctype": self.doctype,
			"name": self.name,
			"display_field": self.display_field,
			"source_field": self.source_field,
			"source_row": self.source_row,
			"suggested_defaults": self.suggested_defaults,
			"required_fields": self.required_fields,
		}


# ---------------------------------------------------------------------------
# Per-DocType minimum-field registry
# ---------------------------------------------------------------------------


# {doctype: (display_field, required_fieldnames, default_factory)}
_MASTER_RULES: dict[str, tuple[str, list[str], Any]] = {
	"Supplier": (
		"supplier_name",
		["supplier_name", "supplier_group"],
		lambda *, name, **_: {
			"supplier_name": name,
			"supplier_group": "All Supplier Groups",
			"supplier_type": "Company",
		},
	),
	"Customer": (
		"customer_name",
		["customer_name", "customer_group"],
		lambda *, name, **_: {
			"customer_name": name,
			"customer_group": "All Customer Groups",
			"customer_type": "Company",
		},
	),
	"Item": (
		"item_name",
		["item_code", "item_name", "item_group"],
		lambda *, name, **_: {
			"item_code": name,
			"item_name": name,
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
		},
	),
	"UOM": (
		"uom_name",
		["uom_name"],
		lambda *, name, **_: {"uom_name": name},
	),
	"Account": (
		"account_name",
		["account_name", "account_type"],
		lambda *, name, company=None, **_: {
			"account_name": name,
			"account_type": "Tax",
			"company": company,
		},
	),
	"Item Group": (
		"item_group_name",
		["item_group_name"],
		lambda *, name, **_: {"item_group_name": name},
	),
	"Supplier Group": (
		"supplier_group_name",
		["supplier_group_name"],
		lambda *, name, **_: {"supplier_group_name": name},
	),
	"Customer Group": (
		"customer_group_name",
		["customer_group_name"],
		lambda *, name, **_: {"customer_group_name": name},
	),
	"Cost Center": (
		"cost_center_name",
		["cost_center_name", "company"],
		lambda *, name, company=None, **_: {
			"cost_center_name": name,
			"company": company,
		},
	),
	"Warehouse": (
		"warehouse_name",
		["warehouse_name", "company"],
		lambda *, name, company=None, **_: {
			"warehouse_name": name,
			"company": company,
		},
	),
	"Currency": ("name", ["name"], lambda *, name, **_: {"name": name}),
}


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------


def detect_prerequisites(
	mapped: MappedDocument,
	*,
	company: str | None = None,
) -> list[MissingMaster]:
	"""Return the de-duplicated list of missing masters.

	The function gracefully degrades when ``frappe`` is unavailable —
	useful for unit tests where the bench isn't running.  In that
	case every Link target is reported as missing.
	"""

	frappe_db = _get_frappe_db()
	link_fields = _link_fields_for_doctype(mapped.doctype)
	header_links = link_fields.get("__header__", {})
	child_links = {k: v for k, v in link_fields.items() if k != "__header__"}

	out: dict[tuple[str, str], MissingMaster] = {}

	# Header-level links
	for fieldname, link_doctype in header_links.items():
		val = mapped.header.get(fieldname)
		if not val or not isinstance(val, str):
			continue
		_record_if_missing(
			out,
			frappe_db,
			doctype=link_doctype,
			name=val,
			source_field=fieldname,
			source_row=None,
			company=company,
		)

	# Item-level links
	for row_idx, row in enumerate(mapped.items or []):
		if not isinstance(row, dict):
			continue
		for ct_field, link_map in child_links.items():
			# Skip child tables that don't apply to items table.  The
			# detector tries every child schema since extracted rows
			# rarely tag themselves with a parent table name.
			_ = ct_field
			for fieldname, link_doctype in link_map.items():
				val = row.get(fieldname)
				if not val or not isinstance(val, str):
					continue
				_record_if_missing(
					out,
					frappe_db,
					doctype=link_doctype,
					name=val,
					source_field=fieldname,
					source_row=row_idx,
					company=company,
				)

	# Taxes — explicit because the rule mapper does not produce a child schema
	for row_idx, row in enumerate(mapped.taxes or []):
		if not isinstance(row, dict):
			continue
		for fieldname in ("account", "account_head"):
			val = row.get(fieldname)
			if not val or not isinstance(val, str):
				continue
			_record_if_missing(
				out,
				frappe_db,
				doctype="Account",
				name=val,
				source_field=f"taxes.{fieldname}",
				source_row=row_idx,
				company=company,
			)
		cc = row.get("cost_center")
		if cc and isinstance(cc, str):
			_record_if_missing(
				out,
				frappe_db,
				doctype="Cost Center",
				name=cc,
				source_field="taxes.cost_center",
				source_row=row_idx,
				company=company,
			)

	return list(out.values())


def lookup_existing(
	mapped: MappedDocument,
	*,
	doctype: str,
	field: str,
) -> dict[str, str | None]:
	"""For each ``mapped.<plural>[i][field]`` value, return the existing
	ERPNext name (or ``None``).

	Used by the card builder to assign ``status: Existing|New`` to the
	Items / Taxes tables in the ConfirmationCard.
	"""

	frappe_db = _get_frappe_db()
	out: dict[str, str | None] = {}
	if frappe_db is None:
		return out

	rows = mapped.taxes if field in {"account", "account_head"} and doctype == "Account" else mapped.items
	for row in rows or []:
		if not isinstance(row, dict):
			continue
		val = row.get(field)
		if not val or not isinstance(val, str) or val in out:
			continue
		out[val] = _resolve_master(frappe_db, doctype, val)
	return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_if_missing(
	out: dict[tuple[str, str], MissingMaster],
	frappe_db: Any,
	*,
	doctype: str,
	name: str,
	source_field: str,
	source_row: int | None,
	company: str | None,
) -> None:
	if doctype not in _MASTER_RULES:
		# Unsupported master — skip rather than block the card.
		return
	key = (doctype, name)
	if key in out:
		return
	if frappe_db is not None and _resolve_master(frappe_db, doctype, name):
		return
	display_field, required_fields, default_factory = _MASTER_RULES[doctype]
	out[key] = MissingMaster(
		doctype=doctype,
		name=name,
		display_field=display_field,
		source_field=source_field,
		source_row=source_row,
		suggested_defaults=default_factory(name=name, company=company),
		required_fields=list(required_fields),
	)


def _resolve_master(frappe_db: Any, doctype: str, name: str) -> str | None:
	"""Best-effort existence lookup that tolerates the bench being absent."""

	try:
		exists = frappe_db.exists(doctype, name)
		if exists:
			return str(exists)
	except Exception:
		return None
	# Try the display field.
	display_field, _, _ = _MASTER_RULES.get(doctype, ("", [], None))
	if display_field and display_field != "name":
		try:
			val = frappe_db.get_value(doctype, {display_field: name}, "name")
			if val:
				return str(val)
		except Exception:
			pass
	return None


def _link_fields_for_doctype(doctype: str) -> dict[str, dict[str, str]]:
	"""Return ``{"__header__": {fieldname: link_doctype}, child_table_field:
	{fieldname: link_doctype}}``.

	Falls back to a hard-coded minimum when the schema cannot be loaded
	(no Frappe available).
	"""

	try:
		schema = get_doctype_schema(doctype)
	except Exception:
		return _hardcoded_links(doctype)

	header: dict[str, str] = {}
	for f in schema.get("fields") or []:
		if (f.get("fieldtype") or "") == "Link":
			header[f["fieldname"]] = f.get("options") or ""

	child: dict[str, dict[str, str]] = {}
	for ct in schema.get("child_tables") or []:
		ct_name = ct.get("fieldname") or ""
		ct_links: dict[str, str] = {}
		for f in ct.get("fields") or []:
			if (f.get("fieldtype") or "") == "Link":
				ct_links[f["fieldname"]] = f.get("options") or ""
		if ct_links:
			child[ct_name] = ct_links

	return {"__header__": header, **child}


def _hardcoded_links(doctype: str) -> dict[str, dict[str, str]]:
	"""Minimum link map used only when Frappe is unavailable (tests)."""

	common_header = {
		"supplier": "Supplier",
		"customer": "Customer",
		"company": "Company",
		"currency": "Currency",
		"cost_center": "Cost Center",
	}
	common_items = {
		"item_code": "Item",
		"uom": "UOM",
		"warehouse": "Warehouse",
		"expense_account": "Account",
		"income_account": "Account",
	}
	return {"__header__": common_header, "items": common_items}


def _get_frappe_db() -> Any:
	try:
		import frappe

		return frappe.db
	except Exception:
		return None


__all__ = [
	"MissingMaster",
	"detect_prerequisites",
	"lookup_existing",
]
