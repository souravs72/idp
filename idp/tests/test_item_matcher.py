# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.idp.mappers.item_matcher` (Phase 24).

Pure-mode tests: we monkey-patch the small Frappe surface the matcher
touches (``frappe.db.exists``, ``frappe.db.get_value``, ``frappe.get_all``)
so the suite runs without a bench.
"""

from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Frappe stub — narrowly tailored to the matcher's lookups
# ---------------------------------------------------------------------------


@pytest.fixture
def matcher_frappe(monkeypatch):
	"""Provide an in-memory Frappe stub for item_matcher tests."""

	state = {
		"items": {
			# name -> {item_name, ...}
			"ITEM-0001": {"item_name": "Widget Mark I"},
			"ITEM-0002": {"item_name": "Office Chair"},
			"ITEM-0003": {"item_name": "Steel Bracket"},
		},
		"item_barcodes": {"8901234567890": "ITEM-0001"},
		"supplier_parts": {"WMK1-OEM": "ITEM-0001"},
	}

	mod = types.ModuleType("frappe")

	class _DB:
		def exists(self, doctype, name):
			if doctype == "Item":
				return name in state["items"]
			return False

		def get_value(self, doctype, filters, fieldname):
			if doctype == "Item":
				if isinstance(filters, dict) and "item_name" in filters:
					for name, row in state["items"].items():
						if row["item_name"] == filters["item_name"]:
							return name
				return None
			if doctype == "Item Barcode":
				if isinstance(filters, dict) and "barcode" in filters:
					return state["item_barcodes"].get(filters["barcode"])
			if doctype == "Item Supplier":
				if isinstance(filters, dict) and "supplier_part_no" in filters:
					return state["supplier_parts"].get(filters["supplier_part_no"])
			return None

	def get_all(doctype, filters=None, fields=None, limit=None):  # noqa: ARG001
		if doctype != "Item":
			return []
		out = []
		for name, row in state["items"].items():
			out.append({"name": name, "item_name": row["item_name"]})
			if limit and len(out) >= limit:
				break
		return out

	import logging

	mod.db = _DB()
	mod.get_all = get_all
	mod.logger = lambda *_a, **_kw: logging.getLogger("idp.test")
	monkeypatch.setitem(sys.modules, "frappe", mod)
	return state


# ---------------------------------------------------------------------------
# Match pipeline
# ---------------------------------------------------------------------------


def test_exact_item_code(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	res = match_single_item({"item_code": "ITEM-0001"})
	assert res.status == "Existing"
	assert res.best_match == "ITEM-0001"
	assert res.match_reason == "exact_code"
	assert res.confidence == 1.0


def test_exact_barcode(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	res = match_single_item({"item_name": "Random Junk", "barcode": "8901234567890"})
	assert res.status == "Existing"
	assert res.best_match == "ITEM-0001"
	assert res.match_reason == "exact_barcode"


def test_exact_item_name(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	res = match_single_item({"item_name": "Office Chair"})
	assert res.status == "Existing"
	assert res.best_match == "ITEM-0002"
	assert res.match_reason == "exact_name"


def test_fuzzy_name_above_threshold(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	# Slight misspelling — should still resolve via fuzzy_name.
	res = match_single_item({"item_name": "Office Chairs"})
	assert res.status == "Existing"
	assert res.best_match == "ITEM-0002"
	assert res.match_reason == "fuzzy_name"
	assert res.confidence >= 0.75


def test_alias_match(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	# Item code that doesn't exist as Item.name but matches a supplier part.
	res = match_single_item({"item_code": "WMK1-OEM"})
	# fuzzy_name on "WMK1-OEM" against the small pool is unlikely to
	# pass the 0.75 threshold, so the alias fallback should fire.
	assert res.status == "Existing"
	assert res.best_match == "ITEM-0001"
	assert res.match_reason == "alias"


def test_no_match_returns_new_with_candidates(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	res = match_single_item({"item_name": "Totally Made-Up Gizmo"})
	assert res.status == "New"
	assert res.best_match is None
	# No floor-passing fuzzy candidates expected for that string.
	assert res.matches == []


def test_match_items_batch_returns_one_result_per_input(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_items

	rows = [
		{"item_code": "ITEM-0001"},
		{"item_name": "Office Chair"},
		{"item_name": "Nonexistent Thing"},
	]
	results = match_items(rows)
	assert len(results) == 3
	assert [r.status for r in results] == ["Existing", "Existing", "New"]


def test_to_dict_shape(matcher_frappe):
	from idp.idp.mappers.item_matcher import match_single_item

	res = match_single_item({"item_code": "ITEM-0001"})
	d = res.to_dict()
	assert set(d.keys()) >= {
		"extracted",
		"matches",
		"best_match",
		"status",
		"confidence",
		"match_reason",
	}
	assert d["matches"][0]["match_reason"] == "exact_code"
	assert d["matches"][0]["item_code"] == "ITEM-0001"


# ---------------------------------------------------------------------------
# is_stock_item heuristic
# ---------------------------------------------------------------------------


def test_guess_is_stock_item_stock_keyword():
	from idp.idp.mappers.mapper import _guess_is_stock_item

	assert _guess_is_stock_item({"description": "Raw material - steel"}) == 1


def test_guess_is_stock_item_service_keyword():
	from idp.idp.mappers.mapper import _guess_is_stock_item

	assert _guess_is_stock_item({"description": "Consultancy Service Fee"}) == 0


def test_guess_is_stock_item_uom_alone_implies_stock():
	from idp.idp.mappers.mapper import _guess_is_stock_item

	assert _guess_is_stock_item({"item_name": "Mystery", "uom": "Nos"}) == 1


def test_guess_is_stock_item_undetermined():
	from idp.idp.mappers.mapper import _guess_is_stock_item

	assert _guess_is_stock_item({"item_name": "Mystery"}) is None
