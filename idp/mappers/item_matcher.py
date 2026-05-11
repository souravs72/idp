# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 24 — Item matcher (extracted ↔ ERPNext Item).

Implements the matching pipeline specified in
``ENHANCEMENT_ROADMAP_v1.md`` §24.1.  For every extracted item row the
matcher walks a five-step pipeline and returns a ranked candidate list
plus a ``status`` of ``"New"`` or ``"Existing"``:

1. Exact match on ``item_code``
2. Exact match on ``barcode`` (when the extracted row carries one)
3. Exact match on ``item_name``
4. Fuzzy match on ``item_name`` (rapidfuzz token-set ratio, falls back
   to stdlib :class:`difflib.SequenceMatcher` if rapidfuzz is missing)
5. Match via ``Item Barcode`` / ``Item Supplier`` alias rows

Each row's ``best_match`` is the top candidate whose score crosses the
configurable ``match_threshold`` (default 0.75).  Candidates above the
floor threshold (0.5) are kept on the result so the UI can offer the
user "Did you mean ...?" picks for rows where auto-match failed.

Design notes
------------
* Pulls a bounded pool of Item rows (``pool_size``, default 1000) so
  the in-process scoring stays linear in the catalogue size.  On very
  large sites callers should pre-filter by ``item_group`` or
  ``brand``.
* Uses ``frappe.get_all`` so user permissions apply.
* Frappe-aware: when run outside a bench (unit tests / CLI) every
  helper short-circuits to an empty result instead of raising.
* Output mirrors the shape consumed by
  :mod:`idp.llm.tools.propose_create_document` so the matcher can
  be plugged in directly as the source of ``item_mapping_suggestions``
  and per-row ``status``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.mappers.item_matcher")

# Threshold above which a candidate is treated as a confirmed match.
DEFAULT_MATCH_THRESHOLD = 0.75
# Floor below which candidates are dropped from the suggestion list.
DEFAULT_FLOOR_THRESHOLD = 0.5
# Hard cap on candidates returned per row (kept aligned with §24.1).
DEFAULT_TOP_N = 5
# Cap on rows pulled from the Item master in a single match pass.
DEFAULT_POOL_SIZE = 1000


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ItemMatchCandidate:
	"""A single candidate row returned by the matcher.

	Attributes:
		item_code: ERPNext ``Item.name`` (the canonical id).
		item_name: ERPNext ``Item.item_name`` (the display label).
		score: Similarity score in ``[0, 1]``.
		match_reason: Provenance tag — one of ``"exact_code"``,
			``"exact_barcode"``, ``"exact_name"``, ``"fuzzy_name"``,
			``"alias"``.
	"""

	item_code: str
	item_name: str
	score: float
	match_reason: str

	def to_dict(self) -> dict:
		return {
			"item_code": self.item_code,
			"item_name": self.item_name,
			"score": round(float(self.score), 4),
			"match_reason": self.match_reason,
		}


@dataclass
class ItemMatchResult:
	"""Outcome of matching a single extracted row.

	Attributes:
		extracted: Original extracted row (verbatim, for traceability).
		matches: Ranked candidates (descending by score).
		best_match: ``item_code`` of the top candidate when its score
			≥ ``match_threshold``; ``None`` otherwise.
		status: ``"Existing"`` when ``best_match`` is set, else ``"New"``.
		confidence: Score of the top candidate (0.0 when no candidates).
		match_reason: ``match_reason`` of the top candidate.
	"""

	extracted: dict
	matches: list[ItemMatchCandidate] = field(default_factory=list)
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
# Scoring helpers (rapidfuzz-or-difflib)
# ---------------------------------------------------------------------------


def _score(needle: str, haystack: str) -> float:
	"""Return a normalised similarity score in ``[0, 1]``.

	Prefers ``rapidfuzz.fuzz.token_set_ratio`` (resilient against word
	reordering / punctuation), falls back to stdlib
	:class:`difflib.SequenceMatcher` when rapidfuzz isn't installed.
	"""

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


def _exists_item_code(item_code: str) -> str | None:
	"""Return the canonical ``Item.name`` if ``item_code`` exists."""
	frappe = _frappe()
	if frappe is None or not item_code:
		return None
	try:
		if frappe.db.exists("Item", item_code):
			return str(item_code)
	except Exception as exc:
		logger.debug(f"item_matcher._exists_item_code({item_code!r}) failed: {exc}")
	return None


def _lookup_by_barcode(barcode: str) -> str | None:
	"""Return ``Item.name`` linked to ``barcode`` via the Item Barcode child."""
	frappe = _frappe()
	if frappe is None or not barcode:
		return None
	try:
		row = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
		if row:
			return str(row)
	except Exception as exc:
		logger.debug(f"item_matcher._lookup_by_barcode({barcode!r}) failed: {exc}")
	return None


def _lookup_by_item_name(item_name: str) -> str | None:
	"""Return ``Item.name`` for an exact ``item_name`` hit."""
	frappe = _frappe()
	if frappe is None or not item_name:
		return None
	try:
		row = frappe.db.get_value("Item", {"item_name": item_name}, "name")
		if row:
			return str(row)
	except Exception as exc:
		logger.debug(f"item_matcher._lookup_by_item_name({item_name!r}) failed: {exc}")
	return None


def _lookup_by_alias(needle: str) -> str | None:
	"""Match against ``Item Supplier.supplier_part_no`` (alias table).

	ERPNext doesn't ship a dedicated "Item Alias" doctype; the closest
	first-class alias surface is ``Item Supplier.supplier_part_no``.
	"""

	frappe = _frappe()
	if frappe is None or not needle:
		return None
	try:
		row = frappe.db.get_value(
			"Item Supplier",
			{"supplier_part_no": needle},
			"parent",
		)
		if row:
			return str(row)
	except Exception as exc:
		logger.debug(f"item_matcher._lookup_by_alias({needle!r}) failed: {exc}")
	return None


def _fetch_item_pool(pool_size: int = DEFAULT_POOL_SIZE) -> list[dict]:
	"""Fetch a bounded pool of Item rows for in-process fuzzy scoring."""

	frappe = _frappe()
	if frappe is None:
		return []
	try:
		rows = frappe.get_all(
			"Item",
			filters={"disabled": 0},
			fields=["name", "item_name"],
			limit=pool_size,
		)
		return list(rows or [])
	except Exception as exc:
		logger.debug(f"item_matcher._fetch_item_pool() failed: {exc}")
		return []


# ---------------------------------------------------------------------------
# Per-row matcher
# ---------------------------------------------------------------------------


def _extract_row_keys(row: dict) -> tuple[str, str, str]:
	"""Pull the (item_code, item_name, barcode) keys from an extracted row.

	The extractor isn't strict about which key carries the human-readable
	name vs. the SKU — we accept the union of likely fields.
	"""

	if not isinstance(row, dict):
		return "", "", ""
	item_code = str(row.get("item_code") or row.get("code") or row.get("sku") or "").strip()
	item_name = str(row.get("item_name") or row.get("item") or row.get("description") or "").strip()
	barcode = str(row.get("barcode") or row.get("ean") or "").strip()
	return item_code, item_name, barcode


def match_single_item(
	row: dict,
	*,
	pool: list[dict] | None = None,
	match_threshold: float = DEFAULT_MATCH_THRESHOLD,
	floor_threshold: float = DEFAULT_FLOOR_THRESHOLD,
	top_n: int = DEFAULT_TOP_N,
) -> ItemMatchResult:
	"""Run the §24.1 pipeline against a single extracted row.

	The caller may pass a precomputed Item ``pool`` to avoid re-querying
	the master on every call — :func:`match_items` does this for batch
	matching.
	"""

	extracted = dict(row) if isinstance(row, dict) else {}
	item_code, item_name, barcode = _extract_row_keys(extracted)

	if pool is None:
		pool = _fetch_item_pool()

	# Step 1 — exact item_code
	resolved = _exists_item_code(item_code)
	if resolved:
		return _hit(extracted, resolved, _resolve_label(resolved, pool), 1.0, "exact_code")

	# Step 2 — exact barcode
	resolved = _lookup_by_barcode(barcode)
	if resolved:
		return _hit(extracted, resolved, _resolve_label(resolved, pool), 1.0, "exact_barcode")

	# Step 3 — exact item_name (against either of the candidate keys
	# the row provides).
	for needle in (item_name, item_code):
		resolved = _lookup_by_item_name(needle) if needle else None
		if resolved:
			return _hit(extracted, resolved, _resolve_label(resolved, pool), 1.0, "exact_name")

	# Step 4 — fuzzy on item_name against the pool.
	needle = item_name or item_code
	candidates: list[ItemMatchCandidate] = []
	if needle and pool:
		for entry in pool:
			label = entry.get("item_name") or entry.get("name") or ""
			name_val = entry.get("name") or ""
			s = _score(needle, label)
			# Short SKU strings often match the canonical name better
			# than the display name, so try both and keep the higher.
			s = max(s, _score(needle, name_val))
			if s >= floor_threshold:
				candidates.append(
					ItemMatchCandidate(
						item_code=str(name_val),
						item_name=str(label) or str(name_val),
						score=float(s),
						match_reason="fuzzy_name",
					)
				)

	# Step 5 — alias / supplier-part-no fallback (only consulted when
	# fuzzy didn't already cross the threshold).
	best_fuzzy = max((c.score for c in candidates), default=0.0)
	if best_fuzzy < match_threshold:
		for needle_alias in (item_code, item_name, barcode):
			if not needle_alias:
				continue
			resolved = _lookup_by_alias(needle_alias)
			if resolved:
				candidates.append(
					ItemMatchCandidate(
						item_code=resolved,
						item_name=_resolve_label(resolved, pool),
						score=1.0,
						match_reason="alias",
					)
				)
				break

	candidates.sort(key=lambda c: c.score, reverse=True)
	candidates = candidates[:top_n]

	if candidates and candidates[0].score >= match_threshold:
		top = candidates[0]
		return ItemMatchResult(
			extracted=extracted,
			matches=candidates,
			best_match=top.item_code,
			status="Existing",
			confidence=top.score,
			match_reason=top.match_reason,
		)

	return ItemMatchResult(
		extracted=extracted,
		matches=candidates,
		best_match=None,
		status="New",
		confidence=candidates[0].score if candidates else 0.0,
		match_reason=None,
	)


def _hit(
	extracted: dict,
	item_code: str,
	item_name: str,
	score: float,
	reason: str,
) -> ItemMatchResult:
	"""Build a result for a Step 1-3 exact hit."""
	candidate = ItemMatchCandidate(
		item_code=item_code,
		item_name=item_name or item_code,
		score=score,
		match_reason=reason,
	)
	return ItemMatchResult(
		extracted=extracted,
		matches=[candidate],
		best_match=item_code,
		status="Existing",
		confidence=score,
		match_reason=reason,
	)


def _resolve_label(item_code: str, pool: list[dict] | None) -> str:
	"""Best-effort resolution of an Item display name from the pool."""
	if not item_code:
		return ""
	for entry in pool or []:
		if entry.get("name") == item_code:
			return str(entry.get("item_name") or item_code)
	# Fall back to a single get_value call.
	frappe = _frappe()
	if frappe is None:
		return item_code
	try:
		val = frappe.db.get_value("Item", item_code, "item_name")
		return str(val) if val else item_code
	except Exception:
		return item_code


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def match_items(
	extracted_items: list[dict],
	company: str | None = None,  # noqa: ARG001 — reserved for company-scoped catalogues
	match_threshold: float = DEFAULT_MATCH_THRESHOLD,
	*,
	floor_threshold: float = DEFAULT_FLOOR_THRESHOLD,
	top_n: int = DEFAULT_TOP_N,
	pool_size: int = DEFAULT_POOL_SIZE,
) -> list[ItemMatchResult]:
	"""Match every extracted item row against the ERPNext Item master.

	See :class:`ItemMatchResult` for the per-row output shape.  ``company``
	is accepted for API symmetry with :func:`match_taxes` and reserved
	for future per-company item filtering — today it is unused.
	"""

	if not extracted_items:
		return []

	pool = _fetch_item_pool(pool_size=pool_size)
	results: list[ItemMatchResult] = []
	for row in extracted_items:
		results.append(
			match_single_item(
				row,
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
	"ItemMatchCandidate",
	"ItemMatchResult",
	"match_items",
	"match_single_item",
]
