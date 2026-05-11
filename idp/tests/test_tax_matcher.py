# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.mappers.tax_matcher` (Phase 24)."""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def tax_frappe(monkeypatch):
	"""Provide an in-memory Frappe stub for tax_matcher tests."""

	state = {
		"accounts": {
			"IGST - ACME": {"account_name": "IGST", "company": "ACME", "is_group": 0},
			"CGST - ACME": {"account_name": "CGST", "company": "ACME", "is_group": 0},
			"VAT 10% - ACME": {"account_name": "VAT 10%", "company": "ACME", "is_group": 0},
		},
	}

	mod = types.ModuleType("frappe")

	class _DB:
		def exists(self, doctype, name):
			if doctype == "Account":
				return name in state["accounts"]
			return False

		def get_value(self, doctype, filters, fieldname):
			if doctype != "Account":
				return None
			if isinstance(filters, str):
				row = state["accounts"].get(filters)
				return row.get(fieldname) if row else None
			if isinstance(filters, dict):
				for name, row in state["accounts"].items():
					if all(row.get(k) == v or (k == "name" and name == v) for k, v in filters.items()):
						if fieldname == "name":
							return name
						return row.get(fieldname)
			return None

	def get_all(doctype, filters=None, fields=None, limit=None):  # noqa: ARG001
		if doctype != "Account":
			return []
		filters = filters or {}
		out = []
		for name, row in state["accounts"].items():
			if filters.get("company") and row.get("company") != filters["company"]:
				continue
			if filters.get("is_group") is not None and row.get("is_group") != filters["is_group"]:
				continue
			out.append(
				{
					"name": name,
					"account_name": row["account_name"],
					"account_type": "Tax",
				}
			)
			if limit and len(out) >= limit:
				break
		return out

	import logging

	mod.db = _DB()
	mod.get_all = get_all
	mod.logger = lambda *_a, **_kw: logging.getLogger("idp.test")
	monkeypatch.setitem(sys.modules, "frappe", mod)
	return state


def test_exact_account_name(tax_frappe):
	from idp.mappers.tax_matcher import match_single_tax

	res = match_single_tax({"account": "IGST"}, company="ACME")
	assert res.status == "Existing"
	assert res.best_match == "IGST - ACME"
	assert res.match_reason == "exact_account_name"


def test_exact_full_name(tax_frappe):
	from idp.mappers.tax_matcher import match_single_tax

	res = match_single_tax({"account": "IGST - ACME"}, company="ACME")
	assert res.status == "Existing"
	assert res.best_match == "IGST - ACME"
	assert res.match_reason == "exact_name"


def test_fuzzy_match(tax_frappe):
	from idp.mappers.tax_matcher import match_single_tax

	# "VAT 10" should match "VAT 10%"
	res = match_single_tax({"account": "VAT 10"}, company="ACME")
	assert res.status == "Existing"
	assert res.best_match == "VAT 10% - ACME"
	assert res.match_reason == "fuzzy_name"


def test_no_match_returns_new(tax_frappe):
	from idp.mappers.tax_matcher import match_single_tax

	res = match_single_tax({"account": "Sales Tax Bermuda"}, company="ACME")
	assert res.status == "New"
	assert res.best_match is None


def test_match_taxes_batch(tax_frappe):
	from idp.mappers.tax_matcher import match_taxes

	rows = [
		{"account": "IGST", "rate": 0.18, "tax_amount": 1800},
		{"account": "Mystery Cess", "rate": 0.05, "tax_amount": 50},
	]
	results = match_taxes(rows, company="ACME")
	assert len(results) == 2
	assert results[0].status == "Existing"
	assert results[1].status == "New"


def test_to_dict_shape(tax_frappe):
	from idp.mappers.tax_matcher import match_single_tax

	res = match_single_tax({"account": "IGST"}, company="ACME")
	d = res.to_dict()
	assert set(d.keys()) >= {
		"extracted",
		"matches",
		"best_match",
		"status",
		"confidence",
		"match_reason",
	}
	assert d["matches"][0]["match_reason"] == "exact_account_name"
	assert d["matches"][0]["account_name"] == "IGST - ACME"
