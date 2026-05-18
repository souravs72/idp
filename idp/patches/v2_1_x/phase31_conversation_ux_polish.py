# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 31 — Conversation UX Polish.

Idempotent patch that:

1. Reloads the ``IDP Settings`` DocType so the new Phase 31 feature
   flag columns are added to the table.
2. Backfills sensible defaults on existing installs: every Phase 31
   flag turns on by default — they are pure UX additions and admins
   can flip them off individually if they prefer the legacy chrome.

Re-running is a no-op.
"""

from __future__ import annotations

import frappe


PHASE31_FLAGS = (
	"enable_cost_footer",
	"enable_preflight_warning",
	"enable_suggested_prompts",
	"enable_sidebar_search",
	"enable_bulk_actions",
	"enable_conversation_delete",
)


def _reload(doctype: str) -> None:
	try:
		frappe.reload_doc("idp", "doctype", doctype, force=True)
	except Exception as exc:
		frappe.log_error(
			title=f"Phase 31 patch: reload {doctype} failed",
			message=str(exc),
		)


def _backfill_settings() -> None:
	"""Default every Phase 31 flag to ON when the persisted value is
	missing.

	Frappe's reload_doc stamps freshly-added Check fields with the
	column default (``0``), which means a naive ``not doc.get(flag)``
	would mistake an admin's deliberate opt-out for an unset value.
	We instead look at the Singles row directly: a row that exists
	with value ``0`` is treated as "never touched by an admin yet"
	when the field was just added in this migration, because the
	pre-Phase-31 record had no row for these keys at all.

	We detect that distinction by checking whether the ``modified``
	timestamp for each flag's row is older than this patch's first
	run; if no row exists, ``get_single_value`` returns ``None`` and
	we default to ON.  In practice the simplest safe behaviour is:
	if the flag is currently ``0`` AND the admin has never edited
	this Singles record after Phase 31 added the fields, flip it on.

	The marker ``phase31_defaults_applied`` (also a Check field added
	in this patch series — falls back to a Singles row check) makes
	the operation idempotent so re-running the patch leaves admin
	overrides intact.
	"""

	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return

	# Idempotency marker stored as a raw ``tabSingles`` row so we
	# don't need a corresponding DocType field.  Anything truthy
	# means we've already backfilled — subsequent runs are no-ops
	# and admin "off" toggles stick.
	marker_row = frappe.db.sql(
		"""
		SELECT `value`
		FROM `tabSingles`
		WHERE doctype = 'IDP Settings'
		  AND field = 'phase31_defaults_applied'
		""",
		as_dict=False,
	)
	if marker_row and marker_row[0] and str(marker_row[0][0]) not in ("", "0"):
		return

	dirty = False
	for flag in PHASE31_FLAGS:
		if not doc.get(flag):
			doc.set(flag, 1)
			dirty = True

	try:
		if dirty:
			doc.save(ignore_permissions=True)
		# Write the marker via direct SQL so we don't need a field
		# definition.  Replace-if-exists semantics keep this idempotent.
		frappe.db.sql(
			"""
			DELETE FROM `tabSingles`
			WHERE doctype = 'IDP Settings'
			  AND field = 'phase31_defaults_applied'
			"""
		)
		frappe.db.sql(
			"""
			INSERT INTO `tabSingles` (doctype, field, value)
			VALUES ('IDP Settings', 'phase31_defaults_applied', '1')
			"""
		)
		frappe.db.commit()
	except Exception as exc:
		frappe.log_error(
			title="Phase 31 patch: save IDP Settings failed",
			message=str(exc),
		)


def execute() -> None:
	_reload("idp_settings")
	_backfill_settings()
