# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 30 — Streaming & Live Progress.

Idempotent patch that:

1. Reloads the IDP Message DocType so the new ``status`` column lands
   on existing rows (default ``complete``).
2. Backfills ``IDP Settings.streaming_enabled = 1`` for installs that
   predate the field.

Re-running is a no-op.
"""

from __future__ import annotations

import frappe


def _reload(doctype: str) -> None:
	try:
		frappe.reload_doc("idp", "doctype", doctype, force=True)
	except Exception as exc:
		frappe.log_error(
			title=f"Phase 30 patch: reload {doctype} failed",
			message=str(exc),
		)


def _backfill_settings() -> None:
	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return
	if doc.get("streaming_enabled") in (None, "", 0):
		doc.set("streaming_enabled", 1)
		try:
			doc.save(ignore_permissions=True)
		except Exception as exc:
			frappe.log_error(
				title="Phase 30 patch: save IDP Settings failed",
				message=str(exc),
			)


def _backfill_status_column() -> None:
	"""Set status='complete' on every pre-existing IDP Message row."""

	try:
		frappe.db.sql(
			"UPDATE `tabIDP Message` SET `status` = 'complete' WHERE `status` IS NULL OR `status` = ''"
		)
	except Exception as exc:
		frappe.log_error(
			title="Phase 30 patch: backfill IDP Message.status failed",
			message=str(exc),
		)


def execute() -> None:
	_reload("idp_message")
	_backfill_status_column()
	_backfill_settings()
