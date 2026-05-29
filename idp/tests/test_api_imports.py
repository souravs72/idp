# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Import-surface smoke tests for Phase 13.

Ensures every whitelisted endpoint is importable and that the audit
and metrics modules expose their documented public API.  These tests
are intentionally lightweight so they run even when no test site is
available (the import goes through a Frappe stub).
"""

from __future__ import annotations

import importlib


# ---------------------------------------------------------------------------
# Core modules
# ---------------------------------------------------------------------------


def test_audit_module_public_surface(frappe_stub):  # noqa: ARG001
	mod = importlib.import_module("idp.core.audit")
	importlib.reload(mod)
	assert callable(mod.log_event)
	assert callable(mod.log_extraction_event)
	assert callable(mod.log_creation_event)
	assert callable(mod.log_comparison_event)
	assert callable(mod.log_bank_event)
	assert callable(mod.get_recent_logs)
	assert "Uploaded" in mod.VALID_STATUSES
	assert "Failed" in mod.VALID_STATUSES


def test_metrics_module_public_surface(frappe_stub):  # noqa: ARG001
	mod = importlib.import_module("idp.core.metrics")
	importlib.reload(mod)
	for name in (
		"extraction_count",
		"extraction_duration",
		"ocr_confidence",
		"validation_failure_rate",
		"record_creation_count",
		"comparison_count",
		"dashboard",
		"get_dashboard",
	):
		assert callable(getattr(mod, name)), f"{name} not callable"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_extract_api_exposes_expected_endpoints(frappe_stub):  # noqa: ARG001
	mod = importlib.import_module("idp.api.extract")
	importlib.reload(mod)
	for name in ("extract_document", "extract_bank_statement_api", "reconcile_bank_statement_api"):
		assert callable(getattr(mod, name))
