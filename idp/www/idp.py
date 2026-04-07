# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Context provider for the IDP Vue SPA entry point.

Serves ``idp/www/idp.html`` with authentication check and boot data
injected as Jinja context variables for the built frontend.
"""

import frappe
from frappe.utils import get_system_timezone

no_cache = 1


def get_context(context):
	"""Build the Jinja context for the IDP SPA."""
	if frappe.session.user == "Guest":
		frappe.throw("Please login to use Intelligent Document Processing", frappe.PermissionError)

	context.boot = get_boot()
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	"""Return boot data for Vite dev server (dev mode only)."""
	if not frappe.conf.developer_mode:
		frappe.throw("This method is only available in developer mode")
	return get_boot()


def get_boot():
	"""Build boot data for the frontend."""
	return frappe._dict(
		{
			"site_name": frappe.local.site,
			"csrf_token": frappe.sessions.get_csrf_token(),
			"user": frappe.session.user,
			"desk_theme": (frappe.db.get_value("User", frappe.session.user, "desk_theme") or "Light").lower(),
			"timezone": {
				"system": get_system_timezone(),
				"user": frappe.db.get_value("User", frappe.session.user, "time_zone")
				or get_system_timezone(),
			},
		}
	)
