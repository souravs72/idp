# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Schema discovery and MappedDocument dataclass.

Provides functions to introspect ERPNext DocType schemas at runtime
via ``frappe.get_meta()`` and a structured result type for the mapping
pipeline.
"""

from dataclasses import dataclass, field

import frappe

from idp.core.constants import EXCLUDED_FIELD_TYPES, EXTRACTABLE_FIELD_TYPES
from idp.core.logger import get_logger

logger = get_logger("idp.mappers")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class MappedDocument:
	"""Result of mapping an extraction to a DocType schema."""

	doctype: str
	header: dict = field(default_factory=dict)  # {fieldname: value}
	items: list[dict] = field(default_factory=list)  # [{fieldname: value}, ...]
	# Phase 20: per-row tax breakdown surfaced separately so the
	# ConfirmationCard can render an Accounts table.  Each entry is
	# ``{account, rate, tax_amount, ...}``.
	taxes: list[dict] = field(default_factory=list)
	unmapped_fields: list[dict] = field(default_factory=list)  # [{label, value}]
	confidence_scores: dict = field(default_factory=dict)  # {fieldname: float}
	warnings: list[str] = field(default_factory=list)
	link_resolutions: dict = field(default_factory=dict)  # {fieldname: {original, resolved}}
	# Phase 29 — Provenance & Confidence Surface:
	# Optional per-field source attribution populated from OCR / hybrid
	# mapper bboxes when available.  Each entry is keyed by the parent
	# fieldname (e.g. ``"supplier"``) or a child-row coordinate string
	# (e.g. ``"items[0].item_code"``) and carries::
	#
	#     {"page": int, "bbox": [x0, y0, x1, y1], "mapper": "rule|llm|hybrid"}
	#
	# ``bbox`` may be absent for LLM-only fields where no source region
	# was recorded; the UI tooltip surfaces this case.
	source_regions: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schema discovery
# ---------------------------------------------------------------------------


def get_doctype_schema(doctype: str) -> dict:
	"""Discover a DocType's field schema via ``frappe.get_meta()``.

	Returns a dict with the parent fields and any child-table schemas::

	        {
	            "doctype": "Purchase Invoice",
	            "fields": [
	                {
	                    "fieldname": "supplier",
	                    "fieldtype": "Link",
	                    "options": "Supplier",
	                    "label": "Supplier",
	                    "reqd": 1,
	                },
	                ...,
	            ],
	            "child_tables": {
	                "items": {"doctype": "Purchase Invoice Item", "parentfield": "items", "fields": [...]}
	            },
	        }
	"""
	meta = frappe.get_meta(doctype)

	parent_fields: list[dict] = []
	child_tables: dict[str, dict] = {}

	for df in meta.fields:
		field_dict = {
			"fieldname": df.fieldname,
			"fieldtype": df.fieldtype,
			"label": df.label or df.fieldname,
			"reqd": df.reqd or 0,
			"options": df.options or "",
		}

		if df.fieldtype in ("Table", "Table MultiSelect"):
			# Discover the child DocType
			child_dt = df.options
			if child_dt:
				child_tables[df.fieldname] = {
					"doctype": child_dt,
					"parentfield": df.fieldname,
					"fields": _get_child_fields(child_dt),
				}
		elif df.fieldtype not in EXCLUDED_FIELD_TYPES:
			parent_fields.append(field_dict)

	return {
		"doctype": doctype,
		"fields": parent_fields,
		"child_tables": child_tables,
	}


def get_extractable_fields(doctype: str) -> list[dict]:
	"""Return only the extractable fields for *doctype*.

	Extractable types: Data, Link, Date, Currency, Float, Int, Select,
	Text, Small Text, Long Text, Check.
	"""
	schema = get_doctype_schema(doctype)
	return [f for f in schema["fields"] if f["fieldtype"] in EXTRACTABLE_FIELD_TYPES]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_child_fields(child_doctype: str) -> list[dict]:
	"""Return extractable fields for a child DocType."""
	try:
		meta = frappe.get_meta(child_doctype)
	except Exception:
		logger.warning(f"Cannot load meta for child DocType: {child_doctype}")
		return []

	fields: list[dict] = []
	for df in meta.fields:
		if df.fieldtype in EXTRACTABLE_FIELD_TYPES:
			fields.append(
				{
					"fieldname": df.fieldname,
					"fieldtype": df.fieldtype,
					"label": df.label or df.fieldname,
					"reqd": df.reqd or 0,
					"options": df.options or "",
				}
			)
	return fields
