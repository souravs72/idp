# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Lightweight fuzzy-match helper for ConfirmationCard suggestions (Phase 20).

Used by :mod:`idp.tools.propose_create_document` to populate
``item_mapping_suggestions`` and ``tax_mapping_suggestions`` so the UI
can offer "Did you mean ...?" picks when a free-text Item/Account from
the document doesn't exactly match an ERPNext record.

Design notes
------------
* Pure stdlib (``difflib.SequenceMatcher``) — no extra dependency.
* Frappe-aware: when running inside a bench, ``suggest_records`` queries
  ``frappe.get_all`` with the user's permissions; otherwise it returns
  an empty list (test/CLI safety).
* Scores are normalised to ``[0, 1]`` and capped at ``top_n`` results.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.mappers.fuzzy_match")


def score(needle: str, haystack: str) -> float:
	"""Return a normalised similarity score in ``[0, 1]``.

	Uses :class:`difflib.SequenceMatcher.ratio`.  Both strings are
	stripped + casefolded so "Office Supplies" and "office supplies"
	score 1.0.
	"""

	if not needle or not haystack:
		return 0.0
	a = str(needle).strip().casefold()
	b = str(haystack).strip().casefold()
	if not a or not b:
		return 0.0
	if a == b:
		return 1.0
	return SequenceMatcher(None, a, b).ratio()


def rank_candidates(
	needle: str,
	candidates: list[str],
	*,
	top_n: int = 5,
	min_score: float = 0.6,
) -> list[dict]:
	"""Rank a precomputed candidate list by similarity to ``needle``.

	Returns ``[{"value": str, "score": float}, ...]`` sorted descending.
	Filters out anything below ``min_score``.
	"""

	if not needle or not candidates:
		return []
	scored: list[tuple[str, float]] = []
	for c in candidates:
		s = score(needle, c)
		if s >= min_score:
			scored.append((c, s))
	scored.sort(key=lambda x: x[1], reverse=True)
	return [{"value": v, "score": round(s, 4)} for v, s in scored[:top_n]]


def suggest_records(
	needle: str,
	doctype: str,
	*,
	display_field: str = "name",
	filters: dict | None = None,
	top_n: int = 5,
	min_score: float = 0.6,
	pool_size: int = 200,
) -> list[dict]:
	"""Query ERPNext for top-N fuzzy matches of ``needle`` in ``doctype``.

	* ``display_field`` is the user-visible label (e.g. ``item_name`` for
	  Item, ``account_name`` for Account); falls back to the row's
	  ``name`` for the returned id.
	* ``filters`` are passed straight to ``frappe.get_all`` (e.g.
	  ``{"company": "Acme"}`` for Account rows).
	* Pulls a pool of up to ``pool_size`` records, then scores them
	  in-process — avoids loading every record on huge sites.

	Returns ``[{"name": str, "label": str, "score": float}, ...]``.
	Empty list when Frappe isn't available or the lookup fails.
	"""

	if not needle:
		return []
	try:
		import frappe
	except ImportError:
		return []

	try:
		fields = ["name"]
		if display_field and display_field != "name":
			fields.append(display_field)
		rows = frappe.get_all(
			doctype,
			filters=filters or {},
			fields=fields,
			limit=pool_size,
		)
	except Exception as exc:
		logger.debug(f"fuzzy_match.suggest_records({doctype!r}) failed: {exc}")
		return []

	scored: list[tuple[str, str, float]] = []
	for row in rows or []:
		name_val = row.get("name") if hasattr(row, "get") else row["name"]
		label_val = row.get(display_field) if display_field else None
		label = label_val or name_val
		s = score(needle, label)
		if s < min_score:
			# Try the raw name too — short codes often miss display-name
			# matching but match the id exactly.
			s = max(s, score(needle, name_val))
		if s >= min_score:
			scored.append((str(name_val), str(label), s))

	scored.sort(key=lambda x: x[2], reverse=True)
	return [{"name": n, "label": label, "score": round(s, 4)} for n, label, s in scored[:top_n]]


def suggest_item(needle: str, *, top_n: int = 5) -> list[dict]:
	"""Convenience wrapper for ``Item`` fuzzy lookup."""

	return suggest_records(
		needle,
		"Item",
		display_field="item_name",
		top_n=top_n,
	)


def suggest_account(
	needle: str,
	*,
	company: str | None = None,
	top_n: int = 5,
) -> list[dict]:
	"""Convenience wrapper for ``Account`` fuzzy lookup, scoped to company."""

	filters: dict[str, Any] = {"is_group": 0}
	if company:
		filters["company"] = company
	return suggest_records(
		needle,
		"Account",
		display_field="account_name",
		filters=filters,
		top_n=top_n,
	)


__all__ = [
	"rank_candidates",
	"score",
	"suggest_account",
	"suggest_item",
	"suggest_records",
]
