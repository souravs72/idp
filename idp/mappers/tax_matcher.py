# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 24 — Tax matcher (extracted account ↔ ERPNext Account).

Companion to :mod:`idp.mappers.item_matcher`.  Walks each extracted
tax row (``{account, rate, tax_amount, ...}``) and assigns a status
(``"New"`` / ``"Existing"``) plus a ranked candidate list of ERPNext
Account names so the ConfirmationCard can render the §24.4 layout:

```
Extracted          | ERPNext Account | Status
"IGST" 18% 1800.00 | IGST - ACME     | Existing
"VAT"  10% 200.00  | -               | New
```

Matching pipeline per row:

1. Exact match on ``Account.name`` (with company-scoped lookup)
2. Exact match on ``Account.account_name`` (scoped to non-group, leaf
   accounts in the company)
3. Fuzzy match on ``account_name`` (rapidfuzz when available, stdlib
   :class:`difflib.SequenceMatcher` otherwise)

Like :mod:`item_matcher`, candidates above the floor threshold (0.5)
are kept on the result so the UI can surface alternatives even when
auto-match failed; the row is only flagged ``Existing`` when the top
score crosses ``match_threshold`` (default 0.75).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.mappers.tax_matcher")

DEFAULT_MATCH_THRESHOLD = 0.75
DEFAULT_FLOOR_THRESHOLD = 0.5
DEFAULT_TOP_N = 5
DEFAULT_POOL_SIZE = 500


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaxMatchCandidate:
	account_name: str  # ERPNext ``Account.name``
	display_name: str  # ``Account.account_name``
	score: float
	match_reason: str  # "exact_name", "exact_account_name", "fuzzy_name"

	def to_dict(self) -> dict:
		return {
			"account_name": self.account_name,
			"display_name": self.display_name,
			"score": round(float(self.score), 4),
			"match_reason": self.match_reason,
		}


@dataclass
class TaxMatchResult:
	extracted: dict
	matches: list[TaxMatchCandidate] = field(default_factory=list)
	best_match: str | None = None
	status: str = "New"
	confidence: float = 0.0
	match_reason: str | None = None

	def to_dict(self) -> dict:
		return {
			"extracted": dict(self.extracted),
			"matches": [c.to_dict() for c in self.matches],
			"best_match": self.best_match,
			"status": self.status,
			"confidence": round(float(self.confidence), 4),
			"match_reason": self.match_reason,
		}


# ---------------------------------------------------------------------------
# Scoring (rapidfuzz-or-difflib)
# ---------------------------------------------------------------------------


def _score(needle: str, haystack: str) -> float:
	if not needle or not haystack:
		return 0.0
	a = str(needle).strip().casefold()
	b = str(haystack).strip().casefold()
	if not a or not b:
		return 0.0
	if a == b:
		return 1.0
	try:
		from rapidfuzz import fuzz  # type: ignore[import-not-found]

		return float(fuzz.token_set_ratio(a, b)) / 100.0
	except Exception:
		from difflib import SequenceMatcher

		return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# Frappe lookups
# ---------------------------------------------------------------------------


def _frappe():
	try:
		import frappe

		return frappe
	except Exception:
		return None


def _resolve_exact_name(account: str, company: str | None) -> str | None:
	"""Return ``Account.name`` if ``account`` already matches verbatim."""
	frappe = _frappe()
	if frappe is None or not account:
		return None
	try:
		filters: dict[str, Any] = {"name": account}
		if company:
			filters["company"] = company
		row = frappe.db.get_value("Account", filters, "name")
		if row:
			return str(row)
		# Some installs store name without the suffix; try the bare check.
		if frappe.db.exists("Account", account):
			return str(account)
	except Exception as exc:
		logger.debug(f"tax_matcher._resolve_exact_name({account!r}) failed: {exc}")
	return None


def _resolve_exact_account_name(account: str, company: str | None) -> str | None:
	"""Match against ``Account.account_name`` (the human label)."""
	frappe = _frappe()
	if frappe is None or not account:
		return None
	try:
		filters: dict[str, Any] = {"account_name": account, "is_group": 0}
		if company:
			filters["company"] = company
		row = frappe.db.get_value("Account", filters, "name")
		if row:
			return str(row)
	except Exception as exc:
		logger.debug(f"tax_matcher._resolve_exact_account_name({account!r}) failed: {exc}")
	return None


def _fetch_account_pool(
	company: str | None,
	pool_size: int = DEFAULT_POOL_SIZE,
) -> list[dict]:
	"""Pull a bounded pool of leaf Account rows for fuzzy scoring."""
	frappe = _frappe()
	if frappe is None:
		return []
	try:
		filters: dict[str, Any] = {"is_group": 0, "disabled": 0}
		if company:
			filters["company"] = company
		rows = frappe.get_all(
			"Account",
			filters=filters,
			fields=["name", "account_name", "account_type"],
			limit=pool_size,
		)
		return list(rows or [])
	except Exception as exc:
		logger.debug(f"tax_matcher._fetch_account_pool({company!r}) failed: {exc}")
		return []


# ---------------------------------------------------------------------------
# Per-row matcher
# ---------------------------------------------------------------------------


def _extract_account_text(row: dict) -> str:
	"""Pull the user-visible account text from a tax row."""
	if not isinstance(row, dict):
		return ""
	return str(
		row.get("account")
		or row.get("account_head")
		or row.get("account_name")
		or row.get("description")
		or ""
	).strip()


def match_single_tax(
	row: dict,
	*,
	company: str | None = None,
	pool: list[dict] | None = None,
	match_threshold: float = DEFAULT_MATCH_THRESHOLD,
	floor_threshold: float = DEFAULT_FLOOR_THRESHOLD,
	top_n: int = DEFAULT_TOP_N,
) -> TaxMatchResult:
	"""Run the §24.3 pipeline against a single extracted tax row."""

	extracted = dict(row) if isinstance(row, dict) else {}
	needle = _extract_account_text(extracted)

	if pool is None:
		pool = _fetch_account_pool(company)

	# Step 1 — exact Account.name
	resolved = _resolve_exact_name(needle, company)
	if resolved:
		return _hit(extracted, resolved, _resolve_label(resolved, pool), 1.0, "exact_name")

	# Step 2 — exact Account.account_name
	resolved = _resolve_exact_account_name(needle, company)
	if resolved:
		return _hit(extracted, resolved, _resolve_label(resolved, pool), 1.0, "exact_account_name")

	# Step 3 — fuzzy on account_name
	candidates: list[TaxMatchCandidate] = []
	if needle and pool:
		for entry in pool:
			label = entry.get("account_name") or entry.get("name") or ""
			name_val = entry.get("name") or ""
			s = _score(needle, label)
			s = max(s, _score(needle, name_val))
			if s >= floor_threshold:
				candidates.append(
					TaxMatchCandidate(
						account_name=str(name_val),
						display_name=str(label) or str(name_val),
						score=float(s),
						match_reason="fuzzy_name",
					)
				)

	candidates.sort(key=lambda c: c.score, reverse=True)
	candidates = candidates[:top_n]

	if candidates and candidates[0].score >= match_threshold:
		top = candidates[0]
		return TaxMatchResult(
			extracted=extracted,
			matches=candidates,
			best_match=top.account_name,
			status="Existing",
			confidence=top.score,
			match_reason=top.match_reason,
		)

	return TaxMatchResult(
		extracted=extracted,
		matches=candidates,
		best_match=None,
		status="New",
		confidence=candidates[0].score if candidates else 0.0,
		match_reason=None,
	)


def _hit(
	extracted: dict,
	account_name: str,
	display_name: str,
	score: float,
	reason: str,
) -> TaxMatchResult:
	candidate = TaxMatchCandidate(
		account_name=account_name,
		display_name=display_name or account_name,
		score=score,
		match_reason=reason,
	)
	return TaxMatchResult(
		extracted=extracted,
		matches=[candidate],
		best_match=account_name,
		status="Existing",
		confidence=score,
		match_reason=reason,
	)


def _resolve_label(account_name: str, pool: list[dict] | None) -> str:
	if not account_name:
		return ""
	for entry in pool or []:
		if entry.get("name") == account_name:
			return str(entry.get("account_name") or account_name)
	frappe = _frappe()
	if frappe is None:
		return account_name
	try:
		val = frappe.db.get_value("Account", account_name, "account_name")
		return str(val) if val else account_name
	except Exception:
		return account_name


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def match_taxes(
	extracted_taxes: list[dict],
	company: str | None = None,
	match_threshold: float = DEFAULT_MATCH_THRESHOLD,
	*,
	floor_threshold: float = DEFAULT_FLOOR_THRESHOLD,
	top_n: int = DEFAULT_TOP_N,
	pool_size: int = DEFAULT_POOL_SIZE,
) -> list[TaxMatchResult]:
	"""Match every extracted tax row against the ERPNext Account master."""

	if not extracted_taxes:
		return []

	pool = _fetch_account_pool(company, pool_size=pool_size)
	results: list[TaxMatchResult] = []
	for row in extracted_taxes:
		results.append(
			match_single_tax(
				row,
				company=company,
				pool=pool,
				match_threshold=match_threshold,
				floor_threshold=floor_threshold,
				top_n=top_n,
			)
		)
	return results


__all__ = [
	"DEFAULT_FLOOR_THRESHOLD",
	"DEFAULT_MATCH_THRESHOLD",
	"DEFAULT_POOL_SIZE",
	"DEFAULT_TOP_N",
	"TaxMatchCandidate",
	"TaxMatchResult",
	"match_single_tax",
	"match_taxes",
]
