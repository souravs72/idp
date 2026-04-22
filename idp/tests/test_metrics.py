# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.metrics`.

We use the ``frappe_stub`` fixture and inject synthetic rows via
``frappe._records`` to validate aggregation logic independently of the
Frappe DB.
"""

from __future__ import annotations

import importlib

import pytest


def _reload_metrics(monkeypatch, frappe_stub):  # noqa: ARG001
	import idp.core.metrics as metrics

	importlib.reload(metrics)
	return metrics


def _seed(frappe_stub, rows):
	"""Populate the stub's in-memory records table."""
	frappe_stub._records.clear()
	frappe_stub._records.extend(rows)


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


def test_percentile_empty_returns_zero(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	assert m._percentile([], 95) == 0.0


def test_percentile_single_value(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	assert m._percentile([42.0], 95) == 42.0


def test_percentile_linear_interpolation(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	# For the list [1..10], the 50th percentile is 5.5.
	vals = [float(i) for i in range(1, 11)]
	assert m._percentile(vals, 50) == pytest.approx(5.5)


def test_percentile_out_of_range_raises(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	with pytest.raises(ValueError):
		m._percentile([1, 2, 3], 150)


# ---------------------------------------------------------------------------
# _duration_stats
# ---------------------------------------------------------------------------


def test_duration_stats_empty(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	s = m._duration_stats([])
	assert s == {"count": 0, "mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}


def test_duration_stats_ignores_none_and_zero(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	s = m._duration_stats([None, 0, 100, 200, 300])
	assert s["count"] == 3
	assert s["mean_ms"] == 200.0
	assert s["max_ms"] == 300.0


# ---------------------------------------------------------------------------
# extraction_count
# ---------------------------------------------------------------------------


def test_extraction_count_groups_by_status_and_doctype(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [
		{"status": "Extracted", "target_doctype": "Purchase Invoice", "processing_time_ms": 100, "ocr_confidence": 0.9, "created_doctype": None, "created_document": None},
		{"status": "Extracted", "target_doctype": "Purchase Invoice", "processing_time_ms": 200, "ocr_confidence": 0.8, "created_doctype": None, "created_document": None},
		{"status": "Failed", "target_doctype": "Sales Invoice", "processing_time_ms": 50, "ocr_confidence": None, "created_doctype": None, "created_document": None},
	])
	out = m.extraction_count(since_hours=None)
	assert out["total"] == 3
	assert out["by_status"]["Extracted"] == 2
	assert out["by_status"]["Failed"] == 1
	assert out["by_doctype"]["Purchase Invoice"] == 2


# ---------------------------------------------------------------------------
# extraction_duration
# ---------------------------------------------------------------------------


def test_extraction_duration_stats(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [
		{"processing_time_ms": 100, "status": "Extracted", "target_doctype": "X", "ocr_confidence": None, "created_doctype": None, "created_document": None},
		{"processing_time_ms": 200, "status": "Extracted", "target_doctype": "X", "ocr_confidence": None, "created_doctype": None, "created_document": None},
		{"processing_time_ms": 300, "status": "Extracted", "target_doctype": "X", "ocr_confidence": None, "created_doctype": None, "created_document": None},
	])
	out = m.extraction_duration(since_hours=None)
	assert out["count"] == 3
	assert out["mean_ms"] == 200.0
	assert out["median_ms"] == 200.0
	assert out["max_ms"] == 300.0


# ---------------------------------------------------------------------------
# ocr_confidence
# ---------------------------------------------------------------------------


def test_ocr_confidence_avg(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [
		{"ocr_confidence": 0.8, "status": "Extracted", "target_doctype": "X", "processing_time_ms": 0, "created_doctype": None, "created_document": None},
		{"ocr_confidence": 0.9, "status": "Extracted", "target_doctype": "X", "processing_time_ms": 0, "created_doctype": None, "created_document": None},
		{"ocr_confidence": None, "status": "Failed", "target_doctype": "X", "processing_time_ms": 0, "created_doctype": None, "created_document": None},
	])
	out = m.ocr_confidence(since_hours=None)
	assert out["count"] == 2
	assert out["avg_confidence"] == pytest.approx(0.85)


def test_ocr_confidence_empty(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [])
	out = m.ocr_confidence(since_hours=None)
	assert out == {"window_hours": None, "count": 0, "avg_confidence": 0.0}


# ---------------------------------------------------------------------------
# validation_failure_rate
# ---------------------------------------------------------------------------


def test_failure_rate_percentage(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [
		{"status": "Extracted", "target_doctype": "X", "processing_time_ms": 0, "ocr_confidence": None, "created_doctype": None, "created_document": None},
		{"status": "Failed", "target_doctype": "X", "processing_time_ms": 0, "ocr_confidence": None, "created_doctype": None, "created_document": None},
		{"status": "Failed", "target_doctype": "X", "processing_time_ms": 0, "ocr_confidence": None, "created_doctype": None, "created_document": None},
		{"status": "Created", "target_doctype": "X", "processing_time_ms": 0, "ocr_confidence": None, "created_doctype": None, "created_document": None},
	])
	out = m.validation_failure_rate(since_hours=None)
	assert out["total"] == 4
	assert out["failed"] == 2
	assert out["rate_pct"] == 50.0


def test_failure_rate_empty(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [])
	out = m.validation_failure_rate(since_hours=None)
	assert out["rate_pct"] == 0.0


# ---------------------------------------------------------------------------
# dashboard bundle
# ---------------------------------------------------------------------------


def test_dashboard_bundles_every_metric(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [])
	out = m.dashboard(since_hours=None)
	for key in (
		"extraction_count",
		"extraction_duration",
		"ocr_confidence",
		"validation_failure_rate",
		"record_creation_count",
		"comparison_count",
	):
		assert key in out


def test_get_dashboard_coerces_bad_window(frappe_stub, monkeypatch):
	m = _reload_metrics(monkeypatch, frappe_stub)
	_seed(frappe_stub, [])
	# Non-numeric string should default to 24 hours (falls back internally).
	out = m.get_dashboard(since_hours="garbage")
	assert "extraction_count" in out
