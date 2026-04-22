# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for reconciliation scoring helpers.

We exercise :func:`_amounts_equal`, :func:`_reference_equal`,
:func:`_days_between`, and :func:`_score_candidate` plus the top-level
:func:`reconcile_bank_statement` when given an explicit candidate pool
(so no Frappe DB is touched).
"""

from __future__ import annotations

import pytest

from idp.idp.bank_reconciliation import (
	ReconciliationMatch,
	_amounts_equal,
	_days_between,
	_reference_equal,
	_score_candidate,
	reconcile_bank_statement,
)
from idp.idp.extractors.bank_statement import BankTransaction


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
	"a,b,expected",
	[
		(100.00, 100.005, True),   # within tolerance
		(100.00, 100.02, False),   # outside tolerance
		(0.0, 0.0, True),
		(-50.0, -50.001, True),
	],
)
def test_amounts_equal(a, b, expected):
	assert _amounts_equal(a, b) is expected


@pytest.mark.parametrize(
	"a,b,expected",
	[
		("UTR001", "utr001", True),
		("000123", "123", True),
		("  CHQ-42  ", "chq-42", True),
		("CHQ-1", "CHQ-2", False),
		(None, "CHQ-1", False),
		("", "CHQ-1", False),
	],
)
def test_reference_equal(a, b, expected):
	assert _reference_equal(a, b) is expected


def test_days_between_absolute():
	assert _days_between("2026-04-10", "2026-04-05") == 5
	assert _days_between("2026-04-05", "2026-04-10") == 5
	assert _days_between(None, "2026-04-10") is None


# ---------------------------------------------------------------------------
# _score_candidate
# ---------------------------------------------------------------------------


def _txn(date_, amount, reference=None):
	if amount >= 0:
		return BankTransaction(
			date=date_, credit=amount, balance=0.0, reference=reference, row_index=0
		)
	return BankTransaction(
		date=date_, debit=abs(amount), balance=0.0, reference=reference, row_index=0
	)


def _cand(date_, amount, reference=None, name="PE-0001"):
	return ReconciliationMatch(
		doctype="Payment Entry",
		name=name,
		posting_date=date_,
		amount=amount,
		reference_no=reference,
	)


def test_score_candidate_reference_match_is_highest():
	t = _txn("2026-04-10", -500.0, reference="UTR999")
	c = _cand("2026-04-10", -500.0, reference="utr999")
	out = _score_candidate(t, c)
	assert out == ("reference", 1.0)


def test_score_candidate_exact_amount_and_close_date():
	t = _txn("2026-04-10", 1000.0)
	c = _cand("2026-04-11", 1000.0)
	match_type, score = _score_candidate(t, c)
	assert match_type == "exact"
	assert 0.9 <= score <= 1.0


def test_score_candidate_partial_beyond_tolerance():
	t = _txn("2026-04-10", 100.0)
	c = _cand("2026-04-20", 100.0)
	match_type, score = _score_candidate(t, c)
	assert match_type == "partial"
	assert 0.5 <= score < 0.75


def test_score_candidate_rejects_amount_mismatch():
	t = _txn("2026-04-10", 100.0)
	c = _cand("2026-04-10", 200.0)
	assert _score_candidate(t, c) is None


def test_score_candidate_rejects_outside_lookup_window():
	t = _txn("2026-04-10", 100.0)
	c = _cand("2025-01-01", 100.0)
	assert _score_candidate(t, c) is None


# ---------------------------------------------------------------------------
# reconcile_bank_statement — consume-once semantics
# ---------------------------------------------------------------------------


def test_reconcile_prefers_reference_and_consumes_candidate():
	txns = [
		_txn("2026-04-05", -500.0, reference="UTR001"),
		_txn("2026-04-05", -500.0, reference="UTR002"),
	]
	candidates = [
		_cand("2026-04-05", -500.0, reference="UTR001", name="PE-A"),
		_cand("2026-04-05", -500.0, reference="UTR002", name="PE-B"),
	]
	result = reconcile_bank_statement(
		transactions=txns,
		bank_account="Bank - TEST",
		candidates=[c.__dict__ for c in candidates],
	)
	assert len(result.matched) == 2
	matched_names = {m.selected.name for m in result.matched}
	assert matched_names == {"PE-A", "PE-B"}


def test_reconcile_multiple_matches_when_two_candidates_tie():
	# Two candidates with the same amount and no discriminating reference.
	t = _txn("2026-04-05", -500.0, reference=None)
	candidates = [
		_cand("2026-04-05", -500.0, reference=None, name="PE-A"),
		_cand("2026-04-05", -500.0, reference=None, name="PE-B"),
	]
	result = reconcile_bank_statement(
		transactions=[t],
		bank_account="Bank - TEST",
		candidates=[c.__dict__ for c in candidates],
	)
	# With two tied exact candidates we should see either multiple_matches
	# or matched (depending on tie-breaking); in either case the total count
	# must still be 1.
	assert result.total_count() == 1


def test_reconcile_unmatched_when_no_candidates():
	t = _txn("2026-04-05", -500.0)
	result = reconcile_bank_statement(
		transactions=[t],
		bank_account="Bank - TEST",
		candidates=[],
	)
	assert len(result.unmatched) == 1
	assert len(result.matched) == 0


def test_reconcile_empty_transactions_short_circuits():
	result = reconcile_bank_statement(
		transactions=[],
		bank_account="Bank - TEST",
		candidates=[],
	)
	assert result.total_count() == 0
	assert "No transactions" in result.summary
