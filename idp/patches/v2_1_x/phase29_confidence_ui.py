# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 29 — Provenance & Confidence Surface.

Idempotent patch that:

1. Reloads the two DocTypes whose JSON definitions gained Phase 29
   fields (IDP Settings, IDP Extraction Template).
2. Backfills the ``show_confidence_dots`` flag on the IDP Settings
   singleton so existing installs default to the new UI.
3. Backfills per-template confidence thresholds on existing
   IDP Extraction Template rows where the admin hasn't customised
   them.

Re-running the patch is a no-op.
"""

from __future__ import annotations

import frappe


_SETTINGS_DEFAULTS = {
	"show_confidence_dots": 1,
}

_TEMPLATE_DEFAULTS = {
	"confidence_amber_threshold": 0.75,
	"confidence_red_threshold": 0.55,
}


def _reload_doctype(module: str, doctype: str) -> None:
	"""Reload a DocType JSON, swallowing failures so the patch never blocks migration."""

	try:
		frappe.reload_doc("idp", "doctype", doctype, force=True)
	except Exception as exc:
		frappe.log_error(
			title=f"Phase 29 patch: reload {doctype} failed",
			message=str(exc),
		)


def _backfill_settings_defaults() -> None:
	"""Set Phase 29 defaults on the IDP Settings singleton when blank."""

	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return
	mutated = False
	for fieldname, default in _SETTINGS_DEFAULTS.items():
		current = doc.get(fieldname)
		if current in (None, "", 0):
			doc.set(fieldname, default)
			mutated = True
	if mutated:
		try:
			doc.save(ignore_permissions=True)
		except Exception as exc:
			frappe.log_error(
				title="Phase 29 patch: backfill IDP Settings failed",
				message=str(exc),
			)


def _backfill_template_defaults() -> None:
	"""Set Phase 29 thresholds on existing IDP Extraction Template rows when blank."""

	try:
		names = frappe.get_all("IDP Extraction Template", pluck="name")
	except Exception:
		return
	for name in names:
		try:
			tpl = frappe.get_doc("IDP Extraction Template", name)
		except Exception:
			continue
		mutated = False
		for fieldname, default in _TEMPLATE_DEFAULTS.items():
			current = tpl.get(fieldname)
			# Float comparison: treat None / 0 / unset as "needs default".
			if current in (None, "", 0) or current == 0.0:
				tpl.set(fieldname, default)
				mutated = True
		if mutated:
			try:
				tpl.save(ignore_permissions=True)
			except Exception as exc:
				frappe.log_error(
					title=f"Phase 29 patch: backfill template {name} failed",
					message=str(exc),
				)


def execute() -> None:
	"""Entry point invoked by ``bench migrate``."""

	for doctype in (
		"IDP Settings",
		"IDP Extraction Template",
	):
		_reload_doctype("idp", doctype)

	_backfill_settings_defaults()
	_backfill_template_defaults()
	frappe.db.commit()
