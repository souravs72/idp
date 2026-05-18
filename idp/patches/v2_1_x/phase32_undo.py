# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 32 — Reversibility / Undo.

Idempotent patch that:

1. Reloads the ``IDP Settings`` DocType so the new
   ``undo_window_minutes`` column is added to the table.
2. Reloads the ``IDP Message`` DocType so the new ``created_doctype``,
   ``created_docname``, and ``undo_deadline`` columns are added.
3. Backfills the default 5-minute undo window on the singleton when
   the field is still unset.

Re-running is a no-op.
"""

from __future__ import annotations

import frappe


def _reload(doctype: str) -> None:
	try:
		frappe.reload_doc("idp", "doctype", doctype, force=True)
	except Exception as exc:
		frappe.log_error(
			title=f"Phase 32 patch: reload {doctype} failed",
			message=str(exc),
		)


def _backfill_settings() -> None:
	"""Default ``undo_window_minutes`` to 5 when the persisted value is
	missing.  Existing admin overrides (including a deliberate 0)
	are preserved."""

	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return

	# Idempotency marker stored in ``tabSingles`` directly so we don't
	# need an extra DocType field for it.
	marker_row = frappe.db.sql(
		"""
		SELECT `value`
		FROM `tabSingles`
		WHERE doctype = 'IDP Settings'
		  AND field = 'phase32_defaults_applied'
		""",
		as_dict=False,
	)
	if marker_row and marker_row[0] and str(marker_row[0][0]) not in ("", "0"):
		return

	dirty = False
	if doc.get("undo_window_minutes") in (None, "", 0):
		# Distinguish "never touched" from "admin set to 0".  We only
		# flip a stored NULL / empty to the default; the explicit 0
		# (no row in tabSingles vs row with value "0") cannot be
		# disambiguated on a fresh field, so we treat unset as
		# default and accept that an admin who wants 0 will set it
		# after the marker is written.
		doc.set("undo_window_minutes", 5)
		dirty = True

	try:
		if dirty:
			doc.save(ignore_permissions=True)
		frappe.db.sql(
			"""
			DELETE FROM `tabSingles`
			WHERE doctype = 'IDP Settings'
			  AND field = 'phase32_defaults_applied'
			"""
		)
		frappe.db.sql(
			"""
			INSERT INTO `tabSingles` (doctype, field, value)
			VALUES ('IDP Settings', 'phase32_defaults_applied', '1')
			"""
		)
		frappe.db.commit()
	except Exception as exc:
		frappe.log_error(
			title="Phase 32 patch: save IDP Settings failed",
			message=str(exc),
		)


def execute() -> None:
	_reload("idp_settings")
	_reload("idp_message")
	_backfill_settings()
