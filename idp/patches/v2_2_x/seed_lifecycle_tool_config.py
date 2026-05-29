# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Seed IDP Tool Configuration rows for the document lifecycle tools.

``search_documents`` is open to all IDP users (the underlying read
permission still gates the data).  ``update_document`` and
``delete_document`` are restricted to ``System Manager`` by default
via the ``allowed_roles`` child table — administrators can broaden
this via the standard UI without code edits.
"""

import frappe


_TOOLS = [
	{
		"tool_name": "search_documents",
		"enabled": 1,
		"requires_confirmation": 0,
		"mutating": 0,
		"allowed_roles": [],
		"notes": "Read-only search across ERPNext doctypes; honours read perms.",
	},
	{
		"tool_name": "update_document",
		"enabled": 1,
		"requires_confirmation": 1,
		"mutating": 1,
		"allowed_roles": ["System Manager"],
		"notes": "Mutating; defaults to dry_run rendering an UpdateCard.",
	},
	{
		"tool_name": "delete_document",
		"enabled": 1,
		"requires_confirmation": 1,
		"mutating": 1,
		"allowed_roles": ["System Manager"],
		"notes": "Destructive; refuses without confirm=true; restorable via undo window.",
	},
]


def execute() -> None:
	if not frappe.db.table_exists("IDP Tool Configuration"):
		return

	for spec in _TOOLS:
		tool_name = spec["tool_name"]
		if frappe.db.exists("IDP Tool Configuration", {"tool_name": tool_name}):
			# Respect any admin overrides made post-install.
			continue
		doc = frappe.new_doc("IDP Tool Configuration")
		doc.tool_name = tool_name
		doc.enabled = spec["enabled"]
		doc.requires_confirmation = spec["requires_confirmation"]
		doc.mutating = spec["mutating"]
		doc.notes = spec["notes"]
		for role in spec.get("allowed_roles", []):
			doc.append("allowed_roles", {"role": role})
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
