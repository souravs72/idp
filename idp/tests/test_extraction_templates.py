# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.advanced.templates`.

Covers the pure-Python behaviour of template hydration, keyword
matching, and value extraction.  Site-backed flows (``load_templates``,
``apply_template`` DB round-trips) live in ``docs/TEST.md`` as bench
console blocks.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# LoadedTemplate.specificity
# ---------------------------------------------------------------------------


def test_loaded_template_specificity(frappe_stub):
	from idp.advanced.templates import LoadedTemplate

	t = LoadedTemplate(
		name="ACME Invoice",
		target_doctype="Purchase Invoice",
		field_mappings={"bill no": "bill_no", "gstin": "tax_id"},
		match_keywords=["ACME", "GSTIN"],
	)
	# 2 keywords * 10 + 2 mappings = 22
	assert t.specificity == 22


def test_loaded_template_specificity_zero_when_empty(frappe_stub):
	from idp.advanced.templates import LoadedTemplate

	t = LoadedTemplate(name="Empty", target_doctype="Sales Invoice")
	assert t.specificity == 0


# ---------------------------------------------------------------------------
# _hydrate
# ---------------------------------------------------------------------------


def test_hydrate_structured_json(frappe_stub):
	from idp.advanced.templates import _hydrate

	row = {
		"name": "T1",
		"target_doctype": "Purchase Invoice",
		"field_mappings": json.dumps(
			{"mappings": {"Bill No": "bill_no"}, "match_keywords": ["ACME", "GSTIN123"]}
		),
		"validation_rules": json.dumps({"required": ["bill_no"]}),
	}
	tmpl = _hydrate(row)
	assert tmpl.name == "T1"
	# keys are lower-cased
	assert tmpl.field_mappings == {"bill no": "bill_no"}
	assert tmpl.match_keywords == ["ACME", "GSTIN123"]
	assert tmpl.validation_rules == {"required": ["bill_no"]}


def test_hydrate_legacy_flat_dict(frappe_stub):
	from idp.advanced.templates import _hydrate

	row = {
		"name": "T2",
		"target_doctype": "Sales Invoice",
		"field_mappings": json.dumps({"Invoice No": "name"}),
		"validation_rules": "",
	}
	tmpl = _hydrate(row)
	assert tmpl.field_mappings == {"invoice no": "name"}
	assert tmpl.match_keywords == []
	assert tmpl.validation_rules == {}


def test_hydrate_malformed_json_returns_empty(frappe_stub):
	from idp.advanced.templates import _hydrate

	row = {
		"name": "T3",
		"target_doctype": "Purchase Invoice",
		"field_mappings": "{not-json",
		"validation_rules": "also-not-json",
	}
	tmpl = _hydrate(row)
	assert tmpl.field_mappings == {}
	assert tmpl.validation_rules == {}


# ---------------------------------------------------------------------------
# _kw_in_text
# ---------------------------------------------------------------------------


def test_kw_in_text_word_boundary(frappe_stub):
	from idp.advanced.templates import _kw_in_text

	assert _kw_in_text("acme", "invoice from acme corp") is True
	# 'acme' should NOT match inside 'acmescope' (word boundary)
	assert _kw_in_text("acme", "invoice from acmescope") is False


def test_kw_in_text_phrase_uses_substring(frappe_stub):
	from idp.advanced.templates import _kw_in_text

	assert _kw_in_text("acme corp", "invoice from acme corp ltd") is True
	assert _kw_in_text("acme corp", "invoice from acme ltd") is False


def test_kw_in_text_empty_keyword_is_false(frappe_stub):
	from idp.advanced.templates import _kw_in_text

	assert _kw_in_text("   ", "some text") is False


# ---------------------------------------------------------------------------
# _extract_value_near
# ---------------------------------------------------------------------------


def test_extract_value_near_finds_tail_after_keyword(frappe_stub):
	from idp.advanced.templates import _extract_value_near

	text = "Header line\nBill No: INV-2026-0042\nOther: 123"
	assert _extract_value_near(text, "Bill No") == "INV-2026-0042"


def test_extract_value_near_returns_none_when_missing(frappe_stub):
	from idp.advanced.templates import _extract_value_near

	assert _extract_value_near("foo bar baz", "missing") is None
