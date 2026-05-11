# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Specialised bank statement extractor.

Bank statements share a predictable tabular structure — date,
description/narration, debit, credit, and running balance — so a
dedicated parser can achieve substantially higher accuracy than the
generic :class:`FieldMapper` used for invoices.

Pipeline:

1. Run the generic :func:`extract_content` to recover text + tables.
2. Identify the transaction table by header row (date / debit / credit
   / balance keywords).
3. Parse each row into a :class:`BankTransaction`.
4. Validate: dates ordered, running balance consistent within tolerance.
5. Return a :class:`BankStatement` bundle.

The module is deliberately framework-light: everything downstream of
``extract_content`` is pure Python and can be unit-tested without
Frappe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from idp.core.exceptions import ExtractionError
from idp.core.logger import get_logger
from idp.extractors.base import ExtractionResult, extract_content

logger = get_logger("idp.extractors.bank_statement")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BankTransaction:
	"""A single row from a bank statement.

	``debit`` / ``credit`` are mutually exclusive — exactly one is
	populated for a normal posting.  ``balance`` is the running balance
	*after* the transaction.
	"""

	date: str  # ISO YYYY-MM-DD
	description: str = ""
	debit: float | None = None
	credit: float | None = None
	balance: float = 0.0
	reference: str | None = None  # cheque / UTR / RRN
	row_index: int = 0  # original row index inside the source table

	@property
	def amount(self) -> float:
		"""Signed amount.  Credits are positive, debits negative."""
		if self.credit is not None:
			return float(self.credit)
		if self.debit is not None:
			return -float(self.debit)
		return 0.0


@dataclass
class BankStatementIssue:
	"""A validation issue flagged against a parsed statement."""

	severity: str  # "warning" | "error"
	message: str
	row_index: int | None = None


@dataclass
class BankStatement:
	"""Parsed bank statement — header metadata + transaction list."""

	transactions: list[BankTransaction] = field(default_factory=list)
	opening_balance: float | None = None
	closing_balance: float | None = None
	account_number: str | None = None
	statement_period_from: str | None = None
	statement_period_to: str | None = None
	currency: str | None = None
	issues: list[BankStatementIssue] = field(default_factory=list)
	metadata: dict = field(default_factory=dict)

	@property
	def total_debits(self) -> float:
		return round(sum(t.debit or 0.0 for t in self.transactions), 2)

	@property
	def total_credits(self) -> float:
		return round(sum(t.credit or 0.0 for t in self.transactions), 2)


# ---------------------------------------------------------------------------
# Column heuristics
# ---------------------------------------------------------------------------

_DATE_KEYWORDS = {"date", "txn date", "transaction date", "value date", "posting date", "dt"}
_DESCRIPTION_KEYWORDS = {
	"description", "narration", "details", "particulars", "transaction details",
	"remarks", "narrative",
}
_DEBIT_KEYWORDS = {"debit", "withdrawal", "dr", "dr.", "withdraw", "paid out", "debit amount"}
_CREDIT_KEYWORDS = {"credit", "deposit", "cr", "cr.", "paid in", "credit amount"}
_BALANCE_KEYWORDS = {"balance", "running balance", "closing balance", "bal"}
_REFERENCE_KEYWORDS = {
	"ref", "reference", "ref no", "ref. no", "reference no", "cheque", "cheque no",
	"chq no", "chq", "utr", "utr no", "rrn", "transaction id", "txn id", "txn ref",
}


def _norm_header(text: str) -> str:
	return re.sub(r"\s+", " ", (text or "").strip().lower())


def _match_header(headers: list[str], keywords: set[str]) -> int | None:
	"""Return the column index whose header matches any keyword, else None."""
	for idx, raw in enumerate(headers):
		h = _norm_header(raw)
		if not h:
			continue
		if h in keywords:
			return idx
		# substring match for partials like "closing balance (inr)"
		for kw in keywords:
			if kw in h:
				return idx
	return None


# ---------------------------------------------------------------------------
# Date / number parsing
# ---------------------------------------------------------------------------

_DATE_FORMATS = (
	"%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
	"%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
	"%d-%b-%y", "%d/%m/%y", "%d-%m-%y",
)


def _parse_date(raw: str) -> str | None:
	"""Parse *raw* into ISO ``YYYY-MM-DD``, or return ``None`` if unparseable."""
	if not raw:
		return None
	cleaned = re.sub(r"\s+", " ", raw.strip())
	for fmt in _DATE_FORMATS:
		try:
			parsed = datetime.strptime(cleaned, fmt).date()
		except ValueError:
			continue
		# Two-digit years default to 2000s; coerce <1950 back up
		if parsed.year < 1950:
			parsed = parsed.replace(year=parsed.year + 100)
		return parsed.isoformat()
	return None


_NUMBER_RE = re.compile(r"[^\d.\-,]")


def _parse_amount(raw: str) -> float | None:
	"""Parse a bank-style amount string into a float, or return ``None``.

	Handles Indian ``1,23,456.78`` grouping, European ``1.234,56``,
	trailing ``CR``/``DR`` markers, and parenthesised negatives.
	"""
	if raw is None:
		return None
	s = str(raw).strip()
	if not s:
		return None

	# Trailing indicator (CR/DR) — strip but note sign
	sign = 1.0
	upper = s.upper()
	if upper.endswith("CR"):
		s = s[:-2].strip()
	elif upper.endswith("DR"):
		s = s[:-2].strip()
		sign = -1.0

	# Parenthesised negatives  "(123.45)"
	if s.startswith("(") and s.endswith(")"):
		s = s[1:-1].strip()
		sign = -1.0

	# European format: last non-digit is "," acting as decimal separator
	if "," in s and "." in s:
		if s.rfind(",") > s.rfind("."):
			s = s.replace(".", "").replace(",", ".")
		else:
			s = s.replace(",", "")
	elif "," in s and "." not in s:
		# Ambiguous — if exactly two digits after the last comma, treat as decimal
		if re.search(r",\d{2}$", s):
			s = s.replace(",", ".")
		else:
			s = s.replace(",", "")

	s = _NUMBER_RE.sub("", s)
	if s in ("", "-", ".", "-."):
		return None
	try:
		return round(float(s) * sign, 2)
	except ValueError:
		return None


# ---------------------------------------------------------------------------
# Table locator
# ---------------------------------------------------------------------------


@dataclass
class _ColumnMap:
	date: int
	description: int | None
	debit: int | None
	credit: int | None
	balance: int | None
	reference: int | None


def _find_transaction_table(
	tables: list[list[list[str]]],
) -> tuple[list[list[str]], _ColumnMap, int] | None:
	"""Scan all tables and return ``(table, column_map, header_row_index)``.

	A transaction table is identified by a header row that contains at
	least a date column and one of debit/credit/balance.
	"""
	for table in tables or []:
		# Inspect up to the first 5 rows to find a header (some statements
		# carry an account summary row above the transactions).
		for header_idx in range(min(5, len(table))):
			headers = [str(c) for c in table[header_idx]]
			cmap = _build_column_map(headers)
			if cmap is not None:
				return table, cmap, header_idx
	return None


def _build_column_map(headers: list[str]) -> _ColumnMap | None:
	date_idx = _match_header(headers, _DATE_KEYWORDS)
	if date_idx is None:
		return None

	debit_idx = _match_header(headers, _DEBIT_KEYWORDS)
	credit_idx = _match_header(headers, _CREDIT_KEYWORDS)
	balance_idx = _match_header(headers, _BALANCE_KEYWORDS)

	# Require at least one amount column OR a balance column; otherwise
	# this is probably not a transaction table.
	if debit_idx is None and credit_idx is None and balance_idx is None:
		return None

	return _ColumnMap(
		date=date_idx,
		description=_match_header(headers, _DESCRIPTION_KEYWORDS),
		debit=debit_idx,
		credit=credit_idx,
		balance=balance_idx,
		reference=_match_header(headers, _REFERENCE_KEYWORDS),
	)


def _cell(row: list, idx: int | None) -> str:
	if idx is None or idx >= len(row):
		return ""
	value = row[idx]
	return "" if value is None else str(value).strip()


# ---------------------------------------------------------------------------
# Metadata scraping (account number, statement period, currency)
# ---------------------------------------------------------------------------

_ACCOUNT_RE = re.compile(
	r"(?:account|a/c|acct)[\s\.:#]*(?:no|number|#)?[\s\.:]*([0-9Xx\*\-\s]{6,})",
	re.IGNORECASE,
)
_PERIOD_RE = re.compile(
	r"(?:statement\s+period|period|from)\s*[:\-]?\s*"
	r"([\d]{1,2}[\-/\.\s][\w]{1,9}[\-/\.\s][\d]{2,4})"
	r"\s*(?:to|-|–|through)\s*"
	r"([\d]{1,2}[\-/\.\s][\w]{1,9}[\-/\.\s][\d]{2,4})",
	re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"\b(INR|USD|EUR|GBP|AUD|CAD|SGD|AED|JPY|CHF)\b")


def _scrape_header_metadata(text: str) -> dict:
	"""Pull account number, statement period, and currency hints from header text."""
	out: dict = {}
	if not text:
		return out

	account = _ACCOUNT_RE.search(text)
	if account:
		raw = re.sub(r"\s+", "", account.group(1))
		out["account_number"] = raw.rstrip("-")

	period = _PERIOD_RE.search(text)
	if period:
		out["statement_period_from"] = _parse_date(period.group(1))
		out["statement_period_to"] = _parse_date(period.group(2))

	currency = _CURRENCY_RE.search(text.upper())
	if currency:
		out["currency"] = currency.group(1)

	return out


# ---------------------------------------------------------------------------
# Row -> BankTransaction
# ---------------------------------------------------------------------------


def _row_to_transaction(row: list, cmap: _ColumnMap, row_index: int) -> BankTransaction | None:
	"""Convert a single table row into a :class:`BankTransaction`, or ``None``.

	Returns ``None`` for rows that lack a parseable date (footers, spacers).
	"""
	date_iso = _parse_date(_cell(row, cmap.date))
	if not date_iso:
		return None

	debit = _parse_amount(_cell(row, cmap.debit)) if cmap.debit is not None else None
	credit = _parse_amount(_cell(row, cmap.credit)) if cmap.credit is not None else None
	balance_val = _parse_amount(_cell(row, cmap.balance)) if cmap.balance is not None else None

	# Some statements combine debit/credit into a single amount column.  If we
	# only found one side and it is negative, flip it to a debit.
	if debit is not None and credit is None and debit < 0:
		debit, credit = -debit, None
	if credit is not None and debit is None and credit < 0:
		debit, credit = -credit, None

	return BankTransaction(
		date=date_iso,
		description=_cell(row, cmap.description),
		debit=debit,
		credit=credit,
		balance=float(balance_val) if balance_val is not None else 0.0,
		reference=_cell(row, cmap.reference) or None,
		row_index=row_index,
	)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_BALANCE_TOLERANCE: float = 0.05  # rupees / cents tolerance on running-balance walk


def _validate(statement: BankStatement) -> None:
	"""Append issues to *statement* for date ordering and balance walks."""
	if not statement.transactions:
		statement.issues.append(
			BankStatementIssue(severity="error", message="No transactions parsed from statement")
		)
		return

	# Date ordering — warn (not error); many statements are chronological-ascending,
	# but some banks print newest-first.
	dates = [t.date for t in statement.transactions]
	if dates != sorted(dates) and dates != sorted(dates, reverse=True):
		statement.issues.append(
			BankStatementIssue(
				severity="warning",
				message="Transaction dates are not strictly ordered — review original",
			)
		)

	# Running balance walk (only meaningful when balance column is present).
	have_balance = any(t.balance not in (0.0, None) for t in statement.transactions)
	if not have_balance:
		return

	# Determine chronological order so the walk is predictable.
	walked = sorted(statement.transactions, key=lambda t: (t.date, t.row_index))
	prev: BankTransaction | None = None
	for txn in walked:
		if prev is not None:
			expected = round(prev.balance + txn.amount, 2)
			if abs(expected - txn.balance) > _BALANCE_TOLERANCE:
				statement.issues.append(
					BankStatementIssue(
						severity="warning",
						message=(
							f"Running balance mismatch at row {txn.row_index}: "
							f"expected {expected:.2f}, got {txn.balance:.2f}"
						),
						row_index=txn.row_index,
					)
				)
		prev = txn

	statement.opening_balance = round(walked[0].balance - walked[0].amount, 2)
	statement.closing_balance = round(walked[-1].balance, 2)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_bank_statement(extraction: ExtractionResult) -> BankStatement:
	"""Parse a pre-extracted :class:`ExtractionResult` into a :class:`BankStatement`.

	This is the pure-Python path — useful for unit tests that want to
	feed in synthetic extraction output without touching the filesystem.
	"""
	tables = extraction.tables or []

	# Gate: no tables in the extraction means we cannot locate transactions.
	located = _find_transaction_table(tables)
	if located is None:
		raise ExtractionError(
			"Could not identify a transaction table in the document.",
			details={
				"tables_found": len(tables),
				"hint": "Bank statement must expose a tabular structure with "
				        "Date and at least one of Debit/Credit/Balance columns.",
			},
		)

	table, cmap, header_idx = located
	statement = BankStatement()

	meta = _scrape_header_metadata(extraction.text or "")
	statement.account_number = meta.get("account_number")
	statement.statement_period_from = meta.get("statement_period_from")
	statement.statement_period_to = meta.get("statement_period_to")
	statement.currency = meta.get("currency")
	statement.metadata = dict(extraction.metadata or {})

	for i, row in enumerate(table):
		if i <= header_idx:
			continue
		txn = _row_to_transaction(row, cmap, row_index=i)
		if txn is not None:
			statement.transactions.append(txn)

	_validate(statement)
	logger.info(
		"Parsed bank statement | transactions=%d issues=%d",
		len(statement.transactions),
		len(statement.issues),
	)
	return statement


def extract_bank_statement(file_url: str, lang: str = "en") -> BankStatement:
	"""Extract a bank statement from a Frappe file URL.

	Args:
		file_url: Frappe file URL (``/private/files/stmt.pdf``).
		lang: OCR language code passed through to the generic extractor.

	Raises:
		ExtractionError: File cannot be resolved or no transaction table found.
	"""
	extraction = extract_content(file_url, lang=lang)
	statement = parse_bank_statement(extraction)
	# Carry the source file identity into metadata for downstream auditing.
	statement.metadata.setdefault("file_url", file_url)
	return statement


# ---------------------------------------------------------------------------
# Serialisation helpers (used by API layer)
# ---------------------------------------------------------------------------


def statement_to_dict(statement: BankStatement) -> dict:
	"""Convert a :class:`BankStatement` to a JSON-serialisable dict."""
	return {
		"account_number": statement.account_number,
		"statement_period_from": statement.statement_period_from,
		"statement_period_to": statement.statement_period_to,
		"currency": statement.currency,
		"opening_balance": statement.opening_balance,
		"closing_balance": statement.closing_balance,
		"total_debits": statement.total_debits,
		"total_credits": statement.total_credits,
		"transaction_count": len(statement.transactions),
		"transactions": [
			{
				"date": t.date,
				"description": t.description,
				"debit": t.debit,
				"credit": t.credit,
				"balance": t.balance,
				"reference": t.reference,
				"row_index": t.row_index,
			}
			for t in statement.transactions
		],
		"issues": [
			{"severity": i.severity, "message": i.message, "row_index": i.row_index}
			for i in statement.issues
		],
		"metadata": statement.metadata,
	}


def transactions_from_dicts(rows: Iterable[dict]) -> list[BankTransaction]:
	"""Rebuild :class:`BankTransaction` objects from JSON-style dicts."""
	result: list[BankTransaction] = []
	for idx, row in enumerate(rows):
		result.append(
			BankTransaction(
				date=str(row.get("date") or ""),
				description=str(row.get("description") or ""),
				debit=_parse_amount(row["debit"]) if row.get("debit") not in (None, "") else None,
				credit=_parse_amount(row["credit"]) if row.get("credit") not in (None, "") else None,
				balance=float(row.get("balance") or 0.0),
				reference=row.get("reference") or None,
				row_index=int(row.get("row_index") or idx),
			)
		)
	return result
