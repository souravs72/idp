# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.idp.advanced.fine_tuning`.

Covers the row formatters (OpenAI / Anthropic / plain) and the
``min_snippet_len`` drop-rule in :func:`export_dataset`.  The
scheduler-driven ``weekly_export`` is exercised in ``docs/TEST.md``.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest


@pytest.fixture
def correction_row():
	return {
		"name": "CORR-2026-000001",
		"target_doctype": "Purchase Invoice",
		"fieldname": "bill_no",
		"extracted_value": "INV42",
		"corrected_value": "INV-42",
		"source_text_snippet": "Bill No: INV-42\nDate: 2026-04-01",
		"supplier_or_customer": "Acme",
		"origin": "rule",
		"creation": "2026-04-01 10:00:00",
	}


# ---------------------------------------------------------------------------
# Row formatters
# ---------------------------------------------------------------------------


def test_to_openai_shape(frappe_stub, correction_row):
	from idp.idp.advanced.fine_tuning import _to_openai

	out = _to_openai(correction_row)
	roles = [m["role"] for m in out["messages"]]
	assert roles == ["system", "user", "assistant"]
	assert "Purchase Invoice" in out["messages"][0]["content"]
	assert "bill_no" in out["messages"][1]["content"]
	assert out["messages"][2]["content"] == "INV-42"


def test_to_anthropic_shape(frappe_stub, correction_row):
	from idp.idp.advanced.fine_tuning import _to_anthropic

	out = _to_anthropic(correction_row)
	assert "system" in out
	assert "Purchase Invoice" in out["system"]
	roles = [m["role"] for m in out["messages"]]
	assert roles == ["user", "assistant"]
	assert out["messages"][1]["content"] == "INV-42"


def test_to_plain_shape(frappe_stub, correction_row):
	from idp.idp.advanced.fine_tuning import _to_plain

	out = _to_plain(correction_row)
	assert out["input"]["doctype"] == "Purchase Invoice"
	assert out["input"]["fieldname"] == "bill_no"
	assert "INV-42" in out["input"]["snippet"]
	assert out["output"] == "INV-42"


def test_to_plain_handles_missing_snippet(frappe_stub):
	from idp.idp.advanced.fine_tuning import _to_plain

	row = {
		"target_doctype": "Sales Invoice",
		"fieldname": "grand_total",
		"corrected_value": "100",
	}
	out = _to_plain(row)
	assert out["input"]["snippet"] == ""
	assert out["output"] == "100"


# ---------------------------------------------------------------------------
# export_dataset
# ---------------------------------------------------------------------------


def test_export_dataset_rejects_unknown_format(frappe_stub, tmp_path):
	from idp.idp.advanced.fine_tuning import export_dataset

	with pytest.raises(ValueError, match="Unknown format"):
		export_dataset(str(tmp_path / "out.jsonl"), format="pytorch")


def test_export_dataset_respects_min_snippet_len(frappe_stub, monkeypatch):
	"""Rows with short snippets must be dropped."""
	from idp.idp.advanced import fine_tuning as ft

	rows = [
		{
			"name": "short",
			"target_doctype": "PI",
			"fieldname": "f",
			"extracted_value": "x",
			"corrected_value": "y",
			"source_text_snippet": "tiny",  # < 20 chars
		},
		{
			"name": "long",
			"target_doctype": "PI",
			"fieldname": "f",
			"extracted_value": "x",
			"corrected_value": "y",
			"source_text_snippet": "this snippet is definitely long enough to survive",
		},
	]
	monkeypatch.setattr(ft, "iter_corrections", lambda **_kw: rows)

	with tempfile.TemporaryDirectory() as tmp:
		path = os.path.join(tmp, "out.jsonl")
		stats = ft.export_dataset(path, format="plain")
		assert stats.total_rows == 1
		with open(path, encoding="utf-8") as fh:
			written = [json.loads(line) for line in fh if line.strip()]
		assert len(written) == 1
		assert written[0]["output"] == "y"
