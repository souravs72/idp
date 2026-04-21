# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Bank reconciliation engine.

Matches a list of parsed :class:`BankTransaction` rows against ERPNext
Payment Entry / Journal Entry records already posted for a given bank
account.  Each input transaction is placed into exactly one of four
buckets:

- **matched**            — exact match on amount + date (within
  ``DATE_TOLERANCE_DAYS``) OR reference number.
- **partially_matched**  — amount matches but date is outside the
  tolerance window.  Flagged for user review.
- **multiple_matches**   — more than one candidate — user must pick.
- **unmatched**          — no corresponding entry found.

The engine is read-only: it never mutates the database.  The API layer
(``idp/api/extract.py``) decides whether to apply matches afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

import frappe
from frappe.utils import flt, getdate

from idp.core.logger import get_logger
from idp.idp.extractors.bank_statement import BankTransaction

logger = get_logger("idp.bank_reconciliation")


# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

DATE_TOLERANCE_DAYS: int = 2
AMOUNT_TOLERANCE: float = 0.01  # +/- 1 paise / cent
LOOKUP_WINDOW_DAYS: int = 30  # how far either side of the txn date we search


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReconciliationMatch:
	"""A single candidate ERPNext record that could match a transaction."""

	doctype: str
	name: str
	posting_date: str
	amount: float
	reference_no: str | None = None
	party: str | None = None
	match_type: str = "exact"  # "exact" | "reference" | "partial"
	score: float = 1.0


@dataclass
class ReconciledTransaction:
	"""One bank-statement row plus its match bucket."""

	transaction: BankTransaction
	status: str = "unmatched"  # matched | partially_matched | multiple_matches | unmatched
	candidates: list[ReconciliationMatch] = field(default_factory=list)
	selected: ReconciliationMatch | None = None
	notes: str | None = None


@dataclass
class ReconciliationResult:
	"""Overall reconciliation output across a whole statement."""

	bank_account: str
	company: str | None = None
	matched: list[ReconciledTransaction] = field(default_factory=list)
	partially_matched: list[ReconciledTransaction] = field(default_factory=list)
	multiple_matches: list[ReconciledTransaction] = field(default_factory=list)
	unmatched: list[ReconciledTransaction] = field(default_factory=list)
	summary: str = ""

	def total_count(self) -> int:
		return (
			len(self.matched)
			+ len(self.partially_matched)
			+ len(self.multiple_matches)
			+ len(self.unmatched)
		)


# ---------------------------------------------------------------------------
# Candidate loading
# ---------------------------------------------------------------------------


def _load_payment_entries(
	bank_account: str,
	company: str | None,
	date_from: str,
	date_to: str,
) -> list[dict]:
	"""Return submitted Payment Entries touching *bank_account* in the window."""
	filters: dict = {
		"docstatus": 1,
		"posting_date": ["between", [date_from, date_to]],
	}
	if company:
		filters["company"] = company

	# A Payment Entry references the bank account either as paid_from (outgoing)
	# or paid_to (incoming).  We load each side separately and union — gives
	# us a clean signed amount without duplicating "Internal Transfer" rows.
	entries: list[dict] = []

	outgoing = frappe.get_all(
		"Payment Entry",
		filters={**filters, "paid_from": bank_account},
		fields=[
			"name", "posting_date", "paid_amount", "received_amount",
			"reference_no", "reference_date", "party", "party_type",
			"payment_type", "paid_from", "paid_to",
		],
	)
	for row in outgoing:
		entries.append({**row, "_direction": "outgoing"})

	incoming = frappe.get_all(
		"Payment Entry",
		filters={**filters, "paid_to": bank_account},
		fields=[
			"name", "posting_date", "paid_amount", "received_amount",
			"reference_no", "reference_date", "party", "party_type",
			"payment_type", "paid_from", "paid_to",
		],
	)
	for row in incoming:
		# Avoid duplicating internal-transfer rows the outgoing query already caught.
		if any(e["name"] == row["name"] for e in entries):
			continue
		entries.append({**row, "_direction": "incoming"})

	return entries


def _payment_entry_to_match(entry: dict) -> ReconciliationMatch:
	"""Convert a Payment Entry row into a :class:`ReconciliationMatch`."""
	direction = entry.get("_direction")
	# Outgoing from bank: negative (money leaves the account)
	# Incoming to bank:   positive (money arrives)
	if direction == "outgoing":
		amount = -flt(entry.get("paid_amount") or 0.0)
	else:
		amount = flt(entry.get("received_amount") or entry.get("paid_amount") or 0.0)

	return ReconciliationMatch(
		doctype="Payment Entry",
		name=entry["name"],
		posting_date=str(entry.get("posting_date") or ""),
		amount=round(amount, 2),
		reference_no=(entry.get("reference_no") or None),
		party=(entry.get("party") or None),
	)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _to_date(value) -> date | None:
	if not value:
		return None
	if isinstance(value, date) and not isinstance(value, datetime):
		return value
	if isinstance(value, datetime):
		return value.date()
	try:
		return getdate(value)
	except Exception:
		return None


def _days_between(a, b) -> int | None:
	da, db = _to_date(a), _to_date(b)
	if da is None or db is None:
		return None
	return abs((da - db).days)


def _amounts_equal(x: float, y: float) -> bool:
	return abs(round(x, 2) - round(y, 2)) <= AMOUNT_TOLERANCE


def _reference_equal(a: str | None, b: str | None) -> bool:
	if not a or not b:
		return False
	# Strip whitespace and leading zeros to handle "000123" vs "123".
	na = a.strip().lstrip("0") or a.strip()
	nb = b.strip().lstrip("0") or b.strip()
	return na.lower() == nb.lower()


def _score_candidate(txn: BankTransaction, cand: ReconciliationMatch) -> tuple[str, float] | None:
	"""Return ``(match_type, score)`` or ``None`` if the candidate is not viable.

	- match_type = "reference": perfect reference + amount tie -> score 1.0
	- match_type = "exact":     amount + date-within-tolerance   -> score 0.9..1.0
	- match_type = "partial":   amount only; date beyond tolerance -> score 0.5..0.75
	"""
	if not _amounts_equal(txn.amount, cand.amount):
		return None

	days = _days_between(txn.date, cand.posting_date)
	if days is None:
		# Cannot place on a timeline — treat as partial.
		return ("partial", 0.5)

	if _reference_equal(txn.reference, cand.reference_no):
		return ("reference", 1.0)

	if days <= DATE_TOLERANCE_DAYS:
		# Closer date => higher score
		score = max(0.9, 1.0 - (days * 0.05))
		return ("exact", round(score, 2))

	if days <= LOOKUP_WINDOW_DAYS:
		# Amount matches, but date is outside the tolerance window
		score = max(0.5, 0.75 - (days * 0.01))
		return ("partial", round(score, 2))

	return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def reconcile_bank_statement(
	transactions: Iterable[BankTransaction],
	bank_account: str,
	company: str | None = None,
	candidates: list[dict] | None = None,
) -> ReconciliationResult:
	"""Reconcile parsed bank transactions against ERPNext records.

	Args:
		transactions: Iterable of :class:`BankTransaction` (from a parsed
			statement).
		bank_account: The ERPNext *Account* name for the bank account
			(e.g. ``"Bank - MEL"``).
		company: Optional company filter to scope the candidate lookup.
		candidates: Optional pre-loaded candidate pool.  When ``None``,
			candidates are fetched from ``Payment Entry`` automatically.
			Supplying your own list is useful for unit tests.

	Returns:
		:class:`ReconciliationResult` grouped by match quality.
	"""
	txns = list(transactions)
	result = ReconciliationResult(bank_account=bank_account, company=company)

	if not txns:
		result.summary = "No transactions supplied."
		return result

	# Load candidate universe once, then filter per transaction.
	if candidates is None:
		dates = [t.date for t in txns if t.date]
		if dates:
			d_min = (_to_date(min(dates)) or date.today()) - timedelta(days=LOOKUP_WINDOW_DAYS)
			d_max = (_to_date(max(dates)) or date.today()) + timedelta(days=LOOKUP_WINDOW_DAYS)
		else:
			today = date.today()
			d_min = today - timedelta(days=LOOKUP_WINDOW_DAYS)
			d_max = today + timedelta(days=LOOKUP_WINDOW_DAYS)

		raw_candidates = _load_payment_entries(
			bank_account=bank_account,
			company=company,
			date_from=d_min.isoformat(),
			date_to=d_max.isoformat(),
		)
		candidate_pool = [_payment_entry_to_match(e) for e in raw_candidates]
	else:
		# Accept either raw dicts or ReconciliationMatch instances.
		candidate_pool = [
			c if isinstance(c, ReconciliationMatch) else ReconciliationMatch(**c)
			for c in candidates
		]

	# A candidate can only be consumed once — track used ones.
	consumed: set[tuple[str, str]] = set()

	for txn in txns:
		rt = ReconciledTransaction(transaction=txn)
		scored: list[tuple[str, float, ReconciliationMatch]] = []

		for cand in candidate_pool:
			key = (cand.doctype, cand.name)
			if key in consumed:
				continue
			s = _score_candidate(txn, cand)
			if s is None:
				continue
			match_type, score = s
			ranked = ReconciliationMatch(
				doctype=cand.doctype,
				name=cand.name,
				posting_date=cand.posting_date,
				amount=cand.amount,
				reference_no=cand.reference_no,
				party=cand.party,
				match_type=match_type,
				score=score,
			)
			scored.append((match_type, score, ranked))

		if not scored:
			rt.status = "unmatched"
			result.unmatched.append(rt)
			continue

		scored.sort(key=lambda s: (s[1], s[0] == "reference"), reverse=True)
		rt.candidates = [m for _, _, m in scored]

		exact_hits = [m for t, _, m in scored if t in ("exact", "reference")]
		if len(exact_hits) == 1:
			rt.selected = exact_hits[0]
			rt.status = "matched"
			consumed.add((rt.selected.doctype, rt.selected.name))
			result.matched.append(rt)
		elif len(exact_hits) > 1:
			rt.status = "multiple_matches"
			rt.notes = f"{len(exact_hits)} exact/reference matches — user must pick"
			result.multiple_matches.append(rt)
		else:
			# Only partial matches found
			rt.selected = scored[0][2]
			rt.status = "partially_matched"
			result.partially_matched.append(rt)

	result.summary = _build_summary(result)
	logger.info(
		"Reconciliation complete | bank_account=%s matched=%d partial=%d multi=%d unmatched=%d",
		bank_account, len(result.matched), len(result.partially_matched),
		len(result.multiple_matches), len(result.unmatched),
	)
	return result


def _build_summary(result: ReconciliationResult) -> str:
	total = result.total_count()
	if total == 0:
		return "No transactions to reconcile."
	m, p, mm, u = (
		len(result.matched), len(result.partially_matched),
		len(result.multiple_matches), len(result.unmatched),
	)
	pct = round((m / total) * 100, 1) if total else 0.0
	return (
		f"{m} matched ({pct}% exact), {p} partial, "
		f"{mm} needs-review, {u} unmatched — {total} total"
	)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _match_to_dict(m: ReconciliationMatch) -> dict:
	return {
		"doctype": m.doctype,
		"name": m.name,
		"posting_date": m.posting_date,
		"amount": m.amount,
		"reference_no": m.reference_no,
		"party": m.party,
		"match_type": m.match_type,
		"score": m.score,
	}


def _reconciled_to_dict(rt: ReconciledTransaction) -> dict:
	return {
		"status": rt.status,
		"transaction": {
			"date": rt.transaction.date,
			"description": rt.transaction.description,
			"debit": rt.transaction.debit,
			"credit": rt.transaction.credit,
			"balance": rt.transaction.balance,
			"reference": rt.transaction.reference,
			"row_index": rt.transaction.row_index,
		},
		"selected": _match_to_dict(rt.selected) if rt.selected else None,
		"candidates": [_match_to_dict(c) for c in rt.candidates],
		"notes": rt.notes,
	}


def result_to_dict(result: ReconciliationResult) -> dict:
	"""JSON-serialisable representation of a :class:`ReconciliationResult`."""
	return {
		"bank_account": result.bank_account,
		"company": result.company,
		"summary": result.summary,
		"counts": {
			"matched": len(result.matched),
			"partially_matched": len(result.partially_matched),
			"multiple_matches": len(result.multiple_matches),
			"unmatched": len(result.unmatched),
			"total": result.total_count(),
		},
		"matched": [_reconciled_to_dict(r) for r in result.matched],
		"partially_matched": [_reconciled_to_dict(r) for r in result.partially_matched],
		"multiple_matches": [_reconciled_to_dict(r) for r in result.multiple_matches],
		"unmatched": [_reconciled_to_dict(r) for r in result.unmatched],
	}
