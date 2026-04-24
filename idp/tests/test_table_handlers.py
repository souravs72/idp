# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.idp.advanced.tables`.

Covers the pure-Python post-processors that run after PP-Structure:
multi-page continuation merging, borderless table detection, and
nested-cell fan-out.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# merge_multipage_tables
# ---------------------------------------------------------------------------


def test_merge_multipage_tables_joins_matching_headers(frappe_stub):
	from idp.idp.advanced.tables import merge_multipage_tables

	page1 = [["Item", "Qty", "Rate"], ["Bolts", "10", "5"]]
	page2 = [["Item", "Qty", "Rate"], ["Nuts", "20", "3"]]
	merged = merge_multipage_tables([page1, page2])
	assert len(merged) == 1
	assert merged[0] == [["Item", "Qty", "Rate"], ["Bolts", "10", "5"], ["Nuts", "20", "3"]]


def test_merge_multipage_tables_keeps_distinct_tables(frappe_stub):
	from idp.idp.advanced.tables import merge_multipage_tables

	tbl_a = [["Item", "Qty"], ["Bolts", "10"]]
	tbl_b = [["Date", "Amount"], ["2026-04-01", "1000"]]
	merged = merge_multipage_tables([tbl_a, tbl_b])
	assert len(merged) == 2


def test_merge_multipage_tables_single_table_passthrough(frappe_stub):
	from idp.idp.advanced.tables import merge_multipage_tables

	tbl = [["A", "B"], ["1", "2"]]
	assert merge_multipage_tables([tbl]) == [tbl]


# ---------------------------------------------------------------------------
# detect_borderless_table
# ---------------------------------------------------------------------------


def test_detect_borderless_table_basic(frappe_stub):
	from idp.idp.advanced.tables import detect_borderless_table

	block = "Item        Qty   Rate\nBolts       10    5\nNuts        20    3\n"
	grid = detect_borderless_table(block)
	assert grid is not None
	assert grid[0][0].lower().startswith("item")
	assert len(grid) == 3  # header + 2 rows


def test_detect_borderless_table_too_few_columns_returns_none(frappe_stub):
	from idp.idp.advanced.tables import detect_borderless_table

	block = "Item    Qty\nBolts   10\n"
	# min_columns defaults to 3
	assert detect_borderless_table(block) is None


def test_detect_borderless_table_single_line_returns_none(frappe_stub):
	from idp.idp.advanced.tables import detect_borderless_table

	assert detect_borderless_table("Only one line here") is None


# ---------------------------------------------------------------------------
# flatten_nested_cells
# ---------------------------------------------------------------------------


def test_flatten_nested_cells_fans_out_newline_separated_values(frappe_stub):
	from idp.idp.advanced.tables import flatten_nested_cells

	tbl = [
		["Item", "Batches"],
		["Bolts", "A1\nA2\nA3"],
	]
	out = flatten_nested_cells(tbl)
	# header + 3 fan-out rows
	assert len(out) == 4
	assert out[1] == ["Bolts", "A1"]
	assert out[3] == ["Bolts", "A3"]


def test_flatten_nested_cells_no_op_on_plain_rows(frappe_stub):
	from idp.idp.advanced.tables import flatten_nested_cells

	tbl = [["Item", "Qty"], ["Bolts", "10"]]
	assert flatten_nested_cells(tbl) == tbl


# ---------------------------------------------------------------------------
# postprocess_tables pipeline
# ---------------------------------------------------------------------------


def test_postprocess_tables_pipeline(frappe_stub):
	from idp.idp.advanced.tables import postprocess_tables

	page1 = [["Item", "Batches"], ["Bolts", "A1\nA2"]]
	page2 = [["Item", "Batches"], ["Nuts", "B1"]]
	out = postprocess_tables([page1, page2])
	# Merged into 1 table, then fan-out on the 'A1\nA2' cell
	assert len(out) == 1
	# header + 2 rows for Bolts (A1, A2) + 1 row for Nuts = 4
	assert len(out[0]) == 4
