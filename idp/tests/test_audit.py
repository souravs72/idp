# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.audit`.

These tests use the ``frappe_stub`` fixture so they do not require
a Frappe site.  They verify:

* Serialisation helpers (_jsonify, _truncate).
* Status vocabulary enforcement.
* Each public wrapper produces the expected persisted shape.
* Failure path never raises.
"""

from __future__ import annotations

import importlib
import json

import pytest


def _reload_audit(monkeypatch, frappe_stub):  # noqa: ARG001 (fixture wiring)
	"""Reload ``idp.core.audit`` under the stub."""
	import idp.core.audit as audit

	importlib.reload(audit)
	return audit


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def test_jsonify_none_returns_none(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	assert audit._jsonify(None) is None


def test_jsonify_dict_roundtrip(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	out = audit._jsonify({"a": 1, "b": [1, 2]})
	assert json.loads(out) == {"a": 1, "b": [1, 2]}


def test_jsonify_non_serialisable_falls_back_to_str(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)

	class Weird:
		def __repr__(self):
			return "<weird>"

	# default=str handles it; result must still be valid JSON.
	out = audit._jsonify(Weird())
	json.loads(out)  # does not raise


def test_truncate_short_unchanged(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	assert audit._truncate("hello") == "hello"


def test_truncate_long_is_cut(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	long = "x" * 3000
	out = audit._truncate(long, limit=100)
	assert out is not None and len(out) == 100
	assert out.endswith("…")


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------


def test_log_event_persists_with_defaults(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	name = audit.log_event(file_url="/private/files/invoice.pdf")
	assert name is not None
	assert len(frappe_stub._records) == 1
	row = frappe_stub._records[0]
	assert row["file_url"] == "/private/files/invoice.pdf"
	assert row["status"] == "Uploaded"
	assert row["user"] == "test@example.com"


def test_log_event_unknown_status_is_coerced(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	# With error_message present -> coerces to "Failed".
	audit.log_event(file_url="/x", status="Garbage", error_message="boom")
	assert frappe_stub._records[-1]["status"] == "Failed"
	# Without error_message -> coerces to "Uploaded".
	audit.log_event(file_url="/y", status="Wrong")
	assert frappe_stub._records[-1]["status"] == "Uploaded"


def test_log_event_missing_file_url_uses_placeholder(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_event(file_url=None)
	assert frappe_stub._records[-1]["file_url"] == "<unknown>"


def test_log_event_disabled_flag_short_circuits(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)

	class _Flagged:
		enable_audit_log = 0

	monkeypatch.setattr(frappe_stub, "get_cached_doc", lambda _name: _Flagged())
	assert audit.log_event(file_url="/x") is None
	assert frappe_stub._records == []


def test_log_event_swallows_insert_errors(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)

	def boom(*_a, **_kw):
		raise RuntimeError("db down")

	monkeypatch.setattr(frappe_stub, "get_doc", boom)
	# Must not raise.
	result = audit.log_event(file_url="/x")
	assert result is None


# ---------------------------------------------------------------------------
# Wrapper functions
# ---------------------------------------------------------------------------


def test_log_extraction_event_success(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_extraction_event(
		file_url="/a.pdf",
		target_doctype="Purchase Invoice",
		success=True,
		processing_time_ms=123,
		confidence=0.92,
		language="en",
	)
	row = frappe_stub._records[-1]
	assert row["status"] == "Extracted"
	assert row["ocr_confidence"] == 0.92
	assert row["processing_time_ms"] == 123


def test_log_extraction_event_failure(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_extraction_event(
		file_url="/bad.pdf",
		target_doctype="Purchase Invoice",
		success=False,
		processing_time_ms=50,
		error_message="OCR timeout",
	)
	row = frappe_stub._records[-1]
	assert row["status"] == "Failed"
	assert row["error_message"] == "OCR timeout"


def test_log_creation_event_records_created_name(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_creation_event(
		target_doctype="Purchase Invoice",
		success=True,
		created_name="PI-0001",
	)
	row = frappe_stub._records[-1]
	assert row["status"] == "Created"
	assert row["created_doctype"] == "Purchase Invoice"
	assert row["created_document"] == "PI-0001"


def test_log_comparison_event_embeds_summary(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_comparison_event(
		file_url="/inv.pdf",
		compare_doctype="Purchase Order",
		compare_docname="PO-42",
		success=True,
		processing_time_ms=80,
		summary="5 matches, 1 discrepancy",
	)
	row = frappe_stub._records[-1]
	assert row["status"] == "Extracted"
	assert row["created_document"] == "PO-42"
	assert "comparison_summary" in row["extraction_data"]


def test_log_bank_event_records_counts(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	audit.log_bank_event(
		file_url="/stmt.pdf",
		success=True,
		processing_time_ms=200,
		transaction_count=3,
		bank_account="Main - TEST",
		matched=2,
		unmatched=1,
	)
	row = frappe_stub._records[-1]
	assert row["status"] == "Extracted"
	payload = json.loads(row["extraction_data"])
	assert payload["transaction_count"] == 3
	assert payload["bank_account"] == "Main - TEST"


# ---------------------------------------------------------------------------
# is_audit_enabled
# ---------------------------------------------------------------------------


def test_is_audit_enabled_defaults_true_when_field_missing(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)
	assert audit.is_audit_enabled() is True


def test_is_audit_enabled_false_when_disabled(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)

	class _Flagged:
		enable_audit_log = 0

	monkeypatch.setattr(frappe_stub, "get_cached_doc", lambda _name: _Flagged())
	assert audit.is_audit_enabled() is False


def test_is_audit_enabled_survives_get_cached_error(frappe_stub, monkeypatch):
	audit = _reload_audit(monkeypatch, frappe_stub)

	def boom(_name):
		raise RuntimeError("missing")

	monkeypatch.setattr(frappe_stub, "get_cached_doc", boom)
	assert audit.is_audit_enabled() is True
