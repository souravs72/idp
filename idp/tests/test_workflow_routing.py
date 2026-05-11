# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.advanced.workflow`.

Covers the pure dataclass behaviour of approver-routing rules and
:class:`RoutingResult`.  Site-backed flows (approver resolution
against a live user table, workflow state transitions, ToDo + email
sending) live in ``docs/TEST.md`` as bench console blocks.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ApproverRule.matches
# ---------------------------------------------------------------------------


def test_approver_rule_matches_within_bounds(frappe_stub):
	from idp.advanced.workflow import ApproverRule

	rule = ApproverRule(doctype="Purchase Invoice", min_amount=0, max_amount=10000)
	assert rule.matches(5000) is True
	assert rule.matches(0) is True
	assert rule.matches(10000) is True


def test_approver_rule_matches_open_upper_bound(frappe_stub):
	from idp.advanced.workflow import ApproverRule

	rule = ApproverRule(doctype="Purchase Invoice", min_amount=10000, max_amount=None)
	assert rule.matches(1_000_000) is True
	assert rule.matches(9999) is False


def test_approver_rule_rejects_outside_range(frappe_stub):
	from idp.advanced.workflow import ApproverRule

	rule = ApproverRule(doctype="Purchase Invoice", min_amount=100, max_amount=500)
	assert rule.matches(50) is False
	assert rule.matches(501) is False


def test_approver_rule_none_amount_matches_only_zero_floor(frappe_stub):
	from idp.advanced.workflow import ApproverRule

	zero_floor = ApproverRule(doctype="PI", min_amount=0, max_amount=None)
	nonzero_floor = ApproverRule(doctype="PI", min_amount=100, max_amount=None)
	assert zero_floor.matches(None) is True
	assert nonzero_floor.matches(None) is False


# ---------------------------------------------------------------------------
# RoutingResult.as_dict
# ---------------------------------------------------------------------------


def test_routing_result_as_dict_defaults(frappe_stub):
	from idp.advanced.workflow import RoutingResult

	result = RoutingResult()
	payload = result.as_dict()
	assert payload == {
		"approver": None,
		"workflow_state": None,
		"todo": None,
		"notification_sent": False,
		"errors": [],
	}


def test_routing_result_collects_errors(frappe_stub):
	from idp.advanced.workflow import RoutingResult

	result = RoutingResult()
	result.errors.append("approver resolution: boom")
	payload = result.as_dict()
	assert payload["errors"] == ["approver resolution: boom"]
