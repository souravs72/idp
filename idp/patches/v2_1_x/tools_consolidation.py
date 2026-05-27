# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 34 — IDP Tools Consolidation: migrate IDP Tool Configuration rows.

Three LLM-exposed tools were retired and merged into two new ones:

  find_matching_record  → merged into compare_document (auto-find via filters)
  list_missing_masters  → merged into resolve_masters   (mode='report')
  create_master         → merged into resolve_masters   (mode='create')
  read_attachment_more  → merged into extract_document  (offset param)

For each retired tool name we:
  1. Rename any enabled/configured rows to the replacement tool name.
  2. Delete duplicate rows if the replacement already exists.
  3. Delete rows for retired names with no natural successor
     (find_matching_record / read_attachment_more have no 1:1 replacement row).
"""

import frappe


_RENAMES = {
	"list_missing_masters": "resolve_masters",
	"create_master": "resolve_masters",
}

_DELETIONS = {
	"find_matching_record",
	"read_attachment_more",
}


def execute() -> None:
	if not frappe.db.table_exists("IDP Tool Configuration"):
		return

	for old_name, new_name in _RENAMES.items():
		old_rows = frappe.get_all(
			"IDP Tool Configuration",
			filters={"tool_name": old_name},
			fields=["name", "tool_name"],
		)
		if not old_rows:
			continue

		new_exists = frappe.db.exists("IDP Tool Configuration", {"tool_name": new_name})

		for row in old_rows:
			if new_exists:
				# Replacement row already configured — drop the old one to avoid duplicates.
				frappe.delete_doc("IDP Tool Configuration", row["name"], force=True)
			else:
				frappe.db.set_value("IDP Tool Configuration", row["name"], "tool_name", new_name)
				new_exists = True  # subsequent old_rows should be deleted

	for old_name in _DELETIONS:
		rows = frappe.get_all("IDP Tool Configuration", filters={"tool_name": old_name}, pluck="name")
		for row_name in rows:
			frappe.delete_doc("IDP Tool Configuration", row_name, force=True)

	frappe.db.commit()
