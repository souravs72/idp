# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Install hooks for the IDP app.

Creates the ``IDP User`` role on first install so that permission checks
in :pymod:`idp.api.permissions` have a role to match against.
"""

import frappe

IDP_USER_ROLE = "IDP User"


def after_install() -> None:
	"""Called by Frappe after the app is installed.

	Safe to call multiple times — the role is only created if missing.
	"""
	_ensure_idp_user_role()
	_seed_prompt_library()


def _seed_prompt_library() -> None:
	"""Install the shipped Phase 15 prompt gallery (idempotent)."""
	try:
		from idp.advanced.prompt_library import seed_builtin_prompts

		seed_builtin_prompts(overwrite=False)
	except Exception as exc:
		# Seeding is optional; never block install on failure.
		frappe.log_error(f"IDP prompt library seed failed: {exc}", "IDP after_install")


def _ensure_idp_user_role() -> None:
	"""Create the *IDP User* role if it does not already exist."""
	if frappe.db.exists("Role", IDP_USER_ROLE):
		return

	role = frappe.new_doc("Role")
	role.role_name = IDP_USER_ROLE
	role.desk_access = 1
	role.insert(ignore_permissions=True)
	frappe.db.commit()
