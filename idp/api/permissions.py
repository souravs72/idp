# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Permission helpers for the IDP app.

Provides :pyfunc:`has_app_permission` consumed by the *add_to_apps_screen*
hook and by the SPA gatekeeper.  Only users with the ``IDP User`` or
``System Manager`` role may see the app entry.
"""

import frappe


IDP_ROLES: tuple[str, ...] = ("IDP User", "System Manager", "Administrator")


def has_app_permission() -> bool:
	"""Return ``True`` if the current user may access the IDP app.

	A user has access when they hold one of the roles listed in
	:data:`IDP_ROLES`.  The Guest user never has access.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return False

	user_roles = set(frappe.get_roles(user))
	return bool(user_roles.intersection(IDP_ROLES))


def has_conversation_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	"""Owner-only permission check for *IDP Conversation* documents.

	System Managers and Administrators may read any conversation for
	audit.  All other users may only access conversations they own.
	"""
	user = user or frappe.session.user

	if user in ("Administrator",):
		return True

	user_roles = set(frappe.get_roles(user))
	if "System Manager" in user_roles and permission_type in ("read", "export", "print", "email", "report"):
		return True

	owner = getattr(doc, "user", None) or getattr(doc, "owner", None)
	return owner == user
