# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.6 — ERPNext workflow integration.

Post-creation hooks that wire an IDP-created document into the host
ERPNext site's workflow stack:

* **Approver routing**   -- assign the created document to an approver
  based on grand_total thresholds configured in IDP Settings.
* **Workflow transition** -- advance a freshly-created document to its
  configured initial workflow state when one exists.
* **Notifications**       -- queue an email to the assigned approver.

All helpers no-op silently when the host site does not have a
matching workflow or approver role.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.advanced.workflow")


# ---------------------------------------------------------------------------
# Approver routing rules
# ---------------------------------------------------------------------------


@dataclass
class ApproverRule:
	"""Threshold-based rule resolving the right approver for a document."""

	doctype: str
	min_amount: float
	max_amount: float | None  # None means "no upper bound"
	role: str | None = None  # Role filter for candidate selection
	user: str | None = None  # Explicit user; wins over role
	notify: bool = True

	def matches(self, amount: float | None) -> bool:
		if amount is None:
			return self.min_amount == 0
		if amount < self.min_amount:
			return False
		if self.max_amount is not None and amount > self.max_amount:
			return False
		return True


@dataclass
class RoutingResult:
	approver: str | None = None
	rule: ApproverRule | None = None
	workflow_state: str | None = None
	todo_name: str | None = None
	notification_sent: bool = False
	errors: list[str] = field(default_factory=list)

	def as_dict(self) -> dict:
		return {
			"approver": self.approver,
			"workflow_state": self.workflow_state,
			"todo": self.todo_name,
			"notification_sent": self.notification_sent,
			"errors": self.errors,
		}


# ---------------------------------------------------------------------------
# Rule loading (from IDP Settings JSON; graceful default when absent)
# ---------------------------------------------------------------------------


def load_rules(doctype: str) -> list[ApproverRule]:
	"""Return approver rules for *doctype* from IDP Settings.

	Expected JSON shape on ``IDP Settings.approver_rules``::

	    [
	        {"doctype": "Purchase Invoice", "min_amount": 0, "max_amount": 10000, "role": "Accounts User"},
	        {
	            "doctype": "Purchase Invoice",
	            "min_amount": 10000,
	            "max_amount": null,
	            "user": "finance@example.com",
	        },
	    ]
	"""
	raw = frappe.db.get_single_value("IDP Settings", "approver_rules") or ""
	if not raw:
		return []
	try:
		rows = json.loads(raw) if isinstance(raw, str) else raw
	except (TypeError, ValueError) as exc:
		logger.warning(f"approver_rules is not valid JSON: {exc}")
		return []

	rules: list[ApproverRule] = []
	for entry in rows or []:
		if entry.get("doctype") != doctype:
			continue
		rules.append(
			ApproverRule(
				doctype=entry["doctype"],
				min_amount=float(entry.get("min_amount") or 0),
				max_amount=float(entry["max_amount"]) if entry.get("max_amount") is not None else None,
				role=entry.get("role"),
				user=entry.get("user"),
				notify=bool(entry.get("notify", True)),
			)
		)
	# Sort by min_amount ascending so the first match is the tightest
	rules.sort(key=lambda r: r.min_amount)
	return rules


# ---------------------------------------------------------------------------
# Approver resolution
# ---------------------------------------------------------------------------


def resolve_approver(doctype: str, amount: float | None) -> tuple[str | None, ApproverRule | None]:
	"""Pick an approver user based on *amount*.

	Returns ``(user_email_or_None, matched_rule_or_None)``.
	"""
	for rule in load_rules(doctype):
		if not rule.matches(amount):
			continue
		if rule.user:
			return rule.user, rule
		if rule.role:
			user = _first_user_with_role(rule.role)
			if user:
				return user, rule
	return None, None


def _first_user_with_role(role: str) -> str | None:
	"""Return the name of the least-recently-used enabled user with *role*."""
	rows = frappe.db.sql(
		"""
		SELECT u.name
		FROM `tabUser` u
		JOIN `tabHas Role` r ON r.parent = u.name
		WHERE u.enabled = 1 AND u.user_type = 'System User'
		  AND r.role = %(role)s
		ORDER BY u.last_active ASC
		LIMIT 1
		""",
		{"role": role},
		as_dict=True,
	)
	return rows[0]["name"] if rows else None


# ---------------------------------------------------------------------------
# Document transitions
# ---------------------------------------------------------------------------


def advance_to_initial_workflow_state(doctype: str, name: str) -> str | None:
	"""If a Workflow is bound to *doctype*, set its ``workflow_state`` field.

	Returns the state name applied, or ``None`` when no workflow exists.
	"""
	workflow_name = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
	if not workflow_name:
		return None

	state_field = frappe.db.get_value("Workflow", workflow_name, "workflow_state_field") or "workflow_state"
	# First state in the workflow = the initial one
	initial = frappe.db.get_value(
		"Workflow Document State",
		{"parent": workflow_name},
		"state",
		order_by="idx asc",
	)
	if not initial:
		return None
	frappe.db.set_value(doctype, name, state_field, initial, update_modified=False)
	logger.info(f"Advanced {doctype}/{name} to workflow state {initial!r}")
	return initial


# ---------------------------------------------------------------------------
# ToDo + notification
# ---------------------------------------------------------------------------


def create_approver_todo(doctype: str, name: str, approver: str, description: str) -> str:
	"""Create a Frappe ToDo for the approver."""
	todo = frappe.new_doc("ToDo")
	todo.allocated_to = approver
	todo.description = description
	todo.reference_type = doctype
	todo.reference_name = name
	todo.status = "Open"
	todo.insert(ignore_permissions=True)
	return todo.name


def send_approver_notification(doctype: str, name: str, approver: str, subject: str, message: str) -> bool:
	"""Queue an email to *approver*; returns ``True`` on success."""
	try:
		frappe.sendmail(
			recipients=[approver],
			subject=subject,
			message=message,
			reference_doctype=doctype,
			reference_name=name,
			now=False,
			delayed=True,
		)
		return True
	except Exception as exc:
		logger.warning(f"Failed to queue notification for {approver}: {exc}")
		return False


# ---------------------------------------------------------------------------
# Orchestrator -- call this from create_document() success path
# ---------------------------------------------------------------------------


def route_created_document(
	doctype: str,
	name: str,
	*,
	amount: float | None = None,
) -> RoutingResult:
	"""Main entry point: resolve approver, transition workflow, notify.

	The input *amount* is used for threshold-based routing.  The function
	is fail-soft: any single step can raise and the remaining steps still
	run where possible, with errors collected on the result.
	"""
	result = RoutingResult()

	# 1. Approver
	try:
		approver, rule = resolve_approver(doctype, amount)
		result.approver = approver
		result.rule = rule
	except Exception as exc:
		result.errors.append(f"approver resolution: {exc}")

	# 2. Workflow state
	try:
		result.workflow_state = advance_to_initial_workflow_state(doctype, name)
	except Exception as exc:
		result.errors.append(f"workflow transition: {exc}")

	# 3. ToDo + email (only when we have an approver)
	if result.approver:
		try:
			result.todo_name = create_approver_todo(
				doctype,
				name,
				result.approver,
				f"Please review {doctype} {name} (amount={amount})",
			)
		except Exception as exc:
			result.errors.append(f"todo: {exc}")

		if result.rule and result.rule.notify:
			try:
				sent = send_approver_notification(
					doctype,
					name,
					result.approver,
					subject=f"[IDP] Review requested: {doctype} {name}",
					message=_render_notification_body(doctype, name, amount),
				)
				result.notification_sent = sent
			except Exception as exc:
				result.errors.append(f"notification: {exc}")

	return result


def _render_notification_body(doctype: str, name: str, amount: float | None) -> str:
	url = frappe.utils.get_url(f"/app/{doctype.lower().replace(' ', '-')}/{name}")
	return (
		f"A new {doctype} has been auto-created by IDP and requires your review.<br><br>"
		f"<b>Document:</b> {name}<br>"
		f"<b>Amount:</b> {amount if amount is not None else 'N/A'}<br>"
		f'<a href="{url}">Open document</a>'
	)
