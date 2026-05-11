# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.7 — Prompt library / template gallery.

A catalogue of LLM system-prompt snippets tuned per industry (and
optionally per DocType).  Two public behaviours:

* :func:`load_prompt` returns the best-match prompt for a given
  ``(industry, target_doctype)`` pair, falling back to Generic when
  a specialised prompt is not available.
* :func:`seed_builtin_prompts` writes the shipped fixtures into the
  database -- called from ``after_install`` and ``after_migrate``.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.advanced.prompt_library")


# ---------------------------------------------------------------------------
# Built-in prompt gallery
# ---------------------------------------------------------------------------


_BUILTINS: list[dict] = [
	{
		"prompt_name": "Generic — Invoice Extraction",
		"industry": "Generic",
		"target_doctype": None,
		"description": "Neutral prompt for any tax-invoice-like document.",
		"prompt_body": (
			"You are a meticulous data-extraction assistant. The user has uploaded a "
			"business document (invoice, PO, quotation). Extract structured fields "
			"that match the target ERPNext DocType schema. Prefer values found verbatim "
			"in the document; never fabricate values. For dates, return ISO YYYY-MM-DD. "
			"For amounts, return bare numbers without currency symbols."
		),
	},
	{
		"prompt_name": "Manufacturing — Purchase Invoice",
		"industry": "Manufacturing",
		"target_doctype": "Purchase Invoice",
		"description": "Supplier bills with BOM, HSN/SAC codes, batch numbers.",
		"prompt_body": (
			"You are processing a manufacturing supplier invoice. Typical fields "
			"include: HSN/SAC codes, batch/lot numbers, UOM (Kg/Ton/Nos/Mtr), GST "
			"breakdowns (CGST/SGST/IGST), and multi-line items with tooling or "
			"material specs. Map every line item individually; do not merge. If you "
			"see a BOM reference, place it in the remarks field."
		),
	},
	{
		"prompt_name": "Retail — Sales Invoice",
		"industry": "Retail",
		"target_doctype": "Sales Invoice",
		"description": "Retail receipts and POS-style invoices.",
		"prompt_body": (
			"You are processing a retail sales invoice. Items typically have: SKU, "
			"short name, qty, unit MRP, discount %, tax-inclusive price. Many "
			"receipts have 'Rounded Total' or 'Payable' fields -- map those to "
			"grand_total. Customer may be anonymous ('Walk-in'); use the "
			"company-default customer when no name is present."
		),
	},
	{
		"prompt_name": "Services — Quotation",
		"industry": "Services",
		"target_doctype": "Quotation",
		"description": "Service industry (consulting, IT services) quotations.",
		"prompt_body": (
			"You are processing a services-industry quotation. Line items typically "
			"describe deliverables (milestones, hours, man-days). Rate may be per "
			"hour or per engagement. Validity / 'valid till' is often critical -- "
			"extract it carefully. Terms often include payment milestones; place "
			"them in the terms field verbatim."
		),
	},
	{
		"prompt_name": "Logistics — Delivery Note",
		"industry": "Logistics",
		"target_doctype": "Delivery Note",
		"description": "Consignment notes, lorry receipts, delivery challans.",
		"prompt_body": (
			"You are processing a logistics/delivery document. Look for: vehicle "
			"number, driver name, consignor, consignee, LR number, e-way bill "
			"number, and gross/tare/net weights. Items are typically enumerated "
			"with their gross weight and package count. Preserve package counts "
			"under qty and weights under custom fields when present."
		),
	},
	{
		"prompt_name": "Healthcare — Sales Invoice",
		"industry": "Healthcare",
		"target_doctype": "Sales Invoice",
		"description": "Hospital / pharmacy invoices.",
		"prompt_body": (
			"You are processing a healthcare billing document. Line items include "
			"consultation fees, tests (with test codes), medicines (with batch and "
			"expiry), and room/stay charges. Patient name and MRN number, if "
			"present, should be placed in customer and a custom patient_mrn field."
		),
	},
	{
		"prompt_name": "Construction — Purchase Order",
		"industry": "Construction",
		"target_doctype": "Purchase Order",
		"description": "Construction / infrastructure POs with WBS and project.",
		"prompt_body": (
			"You are processing a construction purchase order. Items often have "
			"WBS codes, project references, and specifications (grade, diameter, "
			"length). Rate units are often per Kg, per Cu.M, per Mtr. Map the "
			"project reference to the project field when the DocType has one."
		),
	},
	{
		"prompt_name": "Finance — Payment Entry",
		"industry": "Finance",
		"target_doctype": "Payment Entry",
		"description": "Bank-initiated remittance advices / payment vouchers.",
		"prompt_body": (
			"You are processing a payment advice or voucher. Extract: party, "
			"payment date, paid amount, reference number (UTR/NEFT/RTGS/cheque), "
			"bank account (tail-4 digits if masked), and mode of payment. "
			"Reference number accuracy is critical for bank reconciliation."
		),
	},
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_builtin_prompts(*, overwrite: bool = False) -> dict:
	"""Upsert the built-in prompt gallery.

	Returns ``{"created": n, "skipped": n, "updated": n}``.  Safe to call
	repeatedly; respects existing user edits unless ``overwrite=True``.
	"""
	created = updated = skipped = 0
	for entry in _BUILTINS:
		name = entry["prompt_name"]
		exists = frappe.db.exists("IDP Prompt Library", name)

		if exists and not overwrite:
			skipped += 1
			continue

		doc = frappe.get_doc("IDP Prompt Library", name) if exists else frappe.new_doc("IDP Prompt Library")
		doc.prompt_name = name
		doc.industry = entry["industry"]
		doc.target_doctype = entry.get("target_doctype")
		doc.description = entry.get("description") or ""
		doc.prompt_body = entry["prompt_body"]
		doc.enabled = 1

		if exists:
			doc.save(ignore_permissions=True)
			updated += 1
		else:
			doc.insert(ignore_permissions=True)
			created += 1

	logger.info(f"Prompt library seed: {created} created, {updated} updated, {skipped} skipped")
	return {"created": created, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


@dataclass
class PromptSnippet:
	name: str
	industry: str
	target_doctype: str | None
	body: str
	description: str = ""


def load_prompt(industry: str, target_doctype: str | None = None) -> PromptSnippet | None:
	"""Return the best-match prompt for ``(industry, target_doctype)``.

	Lookup order:

	1. industry + exact DocType match
	2. industry only, DocType null
	3. Generic + exact DocType match
	4. Generic, DocType null
	"""
	candidates: list[dict] = []
	for specs in (
		{"industry": industry, "target_doctype": target_doctype, "enabled": 1},
		{"industry": industry, "target_doctype": ["is", "not set"], "enabled": 1},
		{"industry": "Generic", "target_doctype": target_doctype, "enabled": 1},
		{"industry": "Generic", "target_doctype": ["is", "not set"], "enabled": 1},
	):
		if specs["target_doctype"] is None and "is" not in str(specs["target_doctype"]):
			continue  # skip malformed
		candidates = frappe.get_all(
			"IDP Prompt Library",
			filters=specs,
			fields=["name", "industry", "target_doctype", "prompt_body", "description"],
			limit=1,
		)
		if candidates:
			break

	if not candidates:
		return None
	row = candidates[0]
	return PromptSnippet(
		name=row["name"],
		industry=row["industry"],
		target_doctype=row.get("target_doctype"),
		body=row["prompt_body"] or "",
		description=row.get("description") or "",
	)


def list_prompts(industry: str | None = None, enabled_only: bool = True) -> list[dict]:
	"""Return summary metadata for every prompt in the library."""
	filters: dict = {}
	if industry:
		filters["industry"] = industry
	if enabled_only:
		filters["enabled"] = 1
	return frappe.get_all(
		"IDP Prompt Library",
		filters=filters,
		fields=["name", "industry", "target_doctype", "description", "enabled"],
		order_by="industry asc, target_doctype asc",
	)
