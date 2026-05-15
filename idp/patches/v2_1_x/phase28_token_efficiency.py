# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 28 — Token-Efficiency Deep Cuts.

Idempotent patch that:

1. Reloads the five DocTypes whose JSON definitions gained Phase 28
   fields (IDP Settings, IDP Extraction Template, IDP Document Log,
   IDP Tool Configuration, IDP Conversation).
2. Backfills sensible defaults for the new singletons fields so
   existing installs don't surprise admins with all-zero flags.

Re-running the patch is a no-op: each field is checked individually
before being set, and ``reload_doc`` is itself idempotent.
"""

from __future__ import annotations

import frappe


_SETTINGS_DEFAULTS = {
	"page_pre_pass_enabled": 1,
	"mapper_cache_enabled": 1,
	"mapper_cache_ttl_hours": 24,
	"vision_text_threshold": 200,
	"summarise_after_messages": 8,
	"strip_thinking_blocks": 1,
	"mapper_version": 1,
	"te_regression_alert_pct": 15,
}


def _reload_doctype(module: str, doctype: str) -> None:
	"""Reload a DocType JSON, swallowing failures so the patch never blocks migration."""

	try:
		frappe.reload_doc("idp", "doctype", doctype, force=True)
	except Exception as exc:
		frappe.log_error(
			title=f"Phase 28 patch: reload {doctype} failed",
			message=str(exc),
		)


def _backfill_settings_defaults() -> None:
	"""Set Phase 28 defaults on the IDP Settings singleton when blank."""

	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return
	mutated = False
	for fieldname, default in _SETTINGS_DEFAULTS.items():
		# Only seed when the field is absent OR equal to the framework
		# zero-value.  Admins who explicitly toggled the flag retain
		# their choice across re-runs.
		current = doc.get(fieldname)
		if current in (None, "", 0):
			doc.set(fieldname, default)
			mutated = True
	if mutated:
		try:
			doc.save(ignore_permissions=True)
		except Exception as exc:
			frappe.log_error(
				title="Phase 28 patch: backfill IDP Settings failed",
				message=str(exc),
			)


def execute() -> None:
	"""Entry point invoked by ``bench migrate``."""

	for doctype in (
		"IDP Settings",
		"IDP Extraction Template",
		"IDP Document Log",
		"IDP Tool Configuration",
		"IDP Conversation",
	):
		_reload_doctype("idp", doctype)

	_backfill_settings_defaults()
	frappe.db.commit()
