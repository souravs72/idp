# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.idp.extractors.bank_statement`.

Exercises the pure Python helpers (header matching, amount/date
parsing, column map, round-trip serialisation) so Phase 12/13
regressions are caught fast without a Frappe site.
"""

from __future__ import annotations

import pytest

from idp.idp.extractors.bank_statement import (
	BankStatement,
	BankTransaction,
	_build_column_map,
	_match_header,
	_norm_header,
	_parse_amount,
	_parse_date,
	statement_to_dict,
	transactions_from_dicts,
)


# ---------------------------------------------------------------------------
# Header normalisation / matching
# ---------------------------------------------------------------------------


def test_norm_header_strips_punctuation_and_lowercases():
	assert _norm_header("  Transaction Date  ") == "transaction date"


@pytest.mark.parametrize(
	"headers,keywords,expected",
	[
		(["Date", "Narration", "Debit", "Credit", "Balance"], {"debit", "withdrawal"}, 2),
		(["Date", "Narration", "Dr", "Cr", "Balance"], {"debit"}, None),
		(["date", "ref", "credit"], {"credit"}, 2),
	],
)
def test_match_header(headers, keywords, expected):
	assert _match_header(headers, keywords) == expected


# ---------------------------------------------------------------------------
# Amount / Date parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	"raw,expected",
	[
		("1,234.56", 1234.56),
		("(250.00)", -250.00),
		("-75.5", -75.5),
		("", None),
		("n/a", None),
		("   ", None),
	],
)
def test_parse_amount(raw, expected):
	assert _parse_amount(raw) == expected


@pytest.mark.parametrize(
	"raw,expected",
	[
		("2026-04-01", "2026-04-01"),
		("01/04/2026", "2026-04-01"),
		("01-04-2026", "2026-04-01"),
		("1 Apr 2026", "2026-04-01"),
	],
)
def test_parse_date_common_formats(raw, expected):
	assert _parse_date(raw) == expected


def test_parse_date_invalid_returns_none():
	assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Column map
# ---------------------------------------------------------------------------


def test_build_column_map_full_headers():
	headers = ["Date", "Description", "Debit", "Credit", "Balance"]
	cmap = _build_column_map(headers)
	assert cmap is not None
	assert cmap.date == 0
	assert cmap.description == 1
	assert cmap.debit == 2
	assert cmap.credit == 3
	assert cmap.balance == 4


def test_build_column_map_missing_date_returns_none():
	# Without a recognisable date column the map is unusable.
	headers = ["Description", "Debit", "Credit"]
	assert _build_column_map(headers) is None


# ---------------------------------------------------------------------------
# Round-trip serialisation
# ---------------------------------------------------------------------------


def _sample_statement():
	txns = [
		BankTransaction(
			date="2026-04-01",
			description="Payment in",
			debit=None,
			credit=500.0,
			balance=500.0,
			reference="UTR001",
			row_index=0,
		),
		BankTransaction(
			date="2026-04-02",
			description="Outgoing",
			debit=100.0,
			credit=None,
			balance=400.0,
			reference=None,
			row_index=1,
		),
	]
	return BankStatement(
		account_name="My Bank Account",
		statement_period_start="2026-04-01",
		statement_period_end="2026-04-30",
		opening_balance=0.0,
		closing_balance=400.0,
		currency="INR",
		transactions=txns,
		issues=[],
	)


def test_statement_to_dict_roundtrip():
	stmt = _sample_statement()
	payload = statement_to_dict(stmt)
	assert payload["currency"] == "INR"
	assert len(payload["transactions"]) == 2

	recovered = transactions_from_dicts(payload["transactions"])
	assert len(recovered) == 2
	assert recovered[0].credit == 500.0
	assert recovered[1].debit == 100.0
	assert recovered[1].reference is None


def test_transactions_from_dicts_tolerates_partial_rows():
	rows = [
		{"date": "2026-04-01", "credit": 100.0, "balance": 100.0},
		{"date": "2026-04-02", "debit": 50.0, "balance": 50.0, "description": "x"},
	]
	txns = transactions_from_dicts(rows)
	assert len(txns) == 2
	assert txns[0].description == ""
	assert txns[1].description == "x"
