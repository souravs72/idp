# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Tax-row extraction (Phase 20).

The legacy :class:`FieldMapper` collapses taxes into a single
parent-level ``total_taxes_and_charges`` amount.  Phase 20 needs a
*row-level* breakdown so the ConfirmationCard can show each tax line
(CGST 9 %, SGST 9 %, IGST 18 %, ...) with an editable account
mapping.

We never replace the rule mapper's parent-level total — it stays as a
sanity-check value the validator can compare against ``sum(rows)``.

Strategy:

1. Walk the extracted tables looking for one that resembles a tax
   block (header row contains "tax", "rate", "amount", or "account").
2. Fall back to a regex pass over the flat text for the canonical
   "(IGST|CGST|SGST|GST|VAT)\\(<rate>%) <amount>" pattern when no
   table is found.

Each row is normalised into::

    {
        "account": str,  # CGST / IGST / VAT / ... (free-form, fuzzy-mappable later)
        "rate": float | None,  # 0.18 means 18 %
        "tax_amount": float | None,
        "description": str | None,
    }
"""

from __future__ import annotations

import re
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.mappers.tax_extractor")


_TAX_HEADER_TOKENS = ("tax", "rate", "amount", "account", "description", "%")
_TAX_NAME_RE = re.compile(
	r"\b(IGST|CGST|SGST|UTGST|GST|VAT|Service\s*Tax|Sales\s*Tax|TDS|TCS|"
	r"Withholding\s*Tax|Excise|Customs)\b",
	re.IGNORECASE,
)
_TAX_LINE_RE = re.compile(
	r"(IGST|CGST|SGST|UTGST|GST|VAT|TDS|TCS)\s*"
	r"(?:\(\s*([\d.]+)\s*%?\s*\))?\s*"
	r"[₹$€£Rs.]*\s*([\d,]+\.?\d*)",
	re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")
_PERCENT_RE = re.compile(r"([\d.]+)\s*%")


def extract_taxes(
	extracted_text: str | None,
	tables: Any | None,
) -> list[dict]:
	"""Return a list of normalised tax rows.

	Empty list when no tax information is found.  Callers should
	merge this output into ``MappedDocument.taxes``.
	"""

	rows: list[dict] = []
	# 1. Tables — preferred (preserves rates without regex ambiguity).
	if tables:
		rows = _from_tables(tables)
	# 2. Flat text fallback — only when tables yielded nothing.
	if not rows and extracted_text:
		rows = _from_text(extracted_text)
	# Drop duplicates while preserving order (some PDFs repeat headers).
	return _dedupe(rows)


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


def _from_tables(tables: Any) -> list[dict]:
	"""Find a tax-shaped table in *tables* and return its rows."""

	# Tables can arrive as either ``list[list[list[str]]]`` (positional)
	# or a dict like ``{"taxes": [...]}``.  Handle both.
	candidates: list[list[list[str]]] = []
	if isinstance(tables, dict):
		for key, value in tables.items():
			if not isinstance(value, list):
				continue
			if "tax" in str(key).lower() and value:
				candidates.append(value)
		if not candidates:
			candidates = [v for v in tables.values() if isinstance(v, list)]
	elif isinstance(tables, list):
		candidates = [t for t in tables if isinstance(t, list)]
	else:
		return []

	for table in candidates:
		rows = _table_to_tax_rows(table)
		if rows:
			return rows
	return []


def _table_to_tax_rows(table: list[list[str]]) -> list[dict]:
	if not table or len(table) < 2:
		return []
	header = [str(c).strip().lower() for c in (table[0] or [])]
	if not _looks_like_tax_header(header):
		# Fallback: scan every row for a tax-name token; if we find one
		# treat the table as a body without an explicit header.
		if not any(_row_has_tax_name(row) for row in table):
			return []
		header = []

	# Build a column index map.  Missing columns just stay None.
	col_idx = _build_col_index(header)

	rows: list[dict] = []
	body = table[1:] if header else table
	for row in body:
		if not row or all(not str(c).strip() for c in row):
			continue
		row_str = [str(c).strip() for c in row]
		if not _row_has_tax_name(row_str):
			# Some tax tables include subtotal rows ("Total taxes ...")
			# we skip those.
			continue
		account = _pick_str(row_str, col_idx.get("account"))
		description = _pick_str(row_str, col_idx.get("description"))
		rate = _pick_rate(row_str, col_idx.get("rate"))
		amount = _pick_amount(row_str, col_idx.get("amount"))
		# When account column is missing, derive from the first cell
		# that contains a known tax name.
		if not account:
			for cell in row_str:
				m = _TAX_NAME_RE.search(cell or "")
				if m:
					account = m.group(0)
					break
		rows.append(
			{
				"account": account or "",
				"rate": rate,
				"tax_amount": amount,
				"description": description or None,
			}
		)
	return rows


def _looks_like_tax_header(header: list[str]) -> bool:
	if not header:
		return False
	hits = sum(1 for cell in header if any(tok in cell for tok in _TAX_HEADER_TOKENS))
	return hits >= 2


def _row_has_tax_name(row: list[str]) -> bool:
	return any(_TAX_NAME_RE.search(cell or "") for cell in row)


def _build_col_index(header: list[str]) -> dict[str, int]:
	idx: dict[str, int] = {}
	for i, cell in enumerate(header):
		if "account" in cell and "account" not in idx:
			idx["account"] = i
		elif "description" in cell and "description" not in idx:
			idx["description"] = i
		elif "rate" in cell or "%" in cell:
			idx.setdefault("rate", i)
		elif "amount" in cell or "value" in cell or "total" in cell:
			idx.setdefault("amount", i)
	return idx


def _pick_str(row: list[str], i: int | None) -> str:
	if i is None or i >= len(row):
		return ""
	return (row[i] or "").strip()


def _pick_rate(row: list[str], i: int | None) -> float | None:
	cell = _pick_str(row, i) if i is not None else " ".join(row)
	m = _PERCENT_RE.search(cell)
	if m:
		try:
			val = float(m.group(1))
		except ValueError:
			return None
		# Normalise to 0..1 range when the source is a percent.
		return val / 100 if val > 1 else val
	# Bare number — assume already a percentage.
	m2 = _NUMBER_RE.search(cell)
	if m2:
		try:
			val = float(m2.group(0).replace(",", ""))
		except ValueError:
			return None
		return val / 100 if val > 1 else val
	return None


def _pick_amount(row: list[str], i: int | None) -> float | None:
	cell = _pick_str(row, i) if i is not None else ""
	if not cell:
		# Last numeric cell in the row is usually the amount.
		for c in reversed(row):
			m = _NUMBER_RE.search(str(c or ""))
			if m:
				return _safe_float(m.group(0))
		return None
	m = _NUMBER_RE.search(cell)
	return _safe_float(m.group(0)) if m else None


def _safe_float(s: str) -> float | None:
	try:
		return float(s.replace(",", ""))
	except (ValueError, AttributeError):
		return None


# ---------------------------------------------------------------------------
# Text fallback
# ---------------------------------------------------------------------------


def _from_text(text: str) -> list[dict]:
	"""Regex pass over the flat extracted text."""

	rows: list[dict] = []
	for m in _TAX_LINE_RE.finditer(text):
		account = (m.group(1) or "").upper()
		rate = m.group(2)
		amount = m.group(3)
		rate_v: float | None
		try:
			rate_v = float(rate) / 100 if rate is not None else None
			if rate_v is not None and rate_v > 1:
				rate_v = rate_v / 100
		except ValueError:
			rate_v = None
		rows.append(
			{
				"account": account,
				"rate": rate_v,
				"tax_amount": _safe_float(amount) if amount else None,
				"description": None,
			}
		)
	return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe(rows: list[dict]) -> list[dict]:
	seen: set[tuple] = set()
	out: list[dict] = []
	for r in rows:
		key = (
			(r.get("account") or "").strip().casefold(),
			r.get("rate"),
			r.get("tax_amount"),
		)
		if key in seen:
			continue
		seen.add(key)
		out.append(r)
	return out


__all__ = ["extract_taxes"]
