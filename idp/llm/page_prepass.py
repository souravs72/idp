# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Page-aware regex pre-pass (Phase 28 §1).

Cheap regex pass that decides, per page, whether the page contains any
signal a target DocType might care about.  Pages without a signal are
replaced in the LLM context with a short placeholder while the original
text stays in storage and remains addressable via
``read_attachment_more``.

Design notes:

* Patterns are intentionally permissive — we'd rather keep a page
  with a coincidental match than drop one with a real signal we don't
  recognise.  False negatives cost extraction accuracy; false
  positives only cost a handful of tokens.
* Per-DocType pattern sets live in :data:`_BUILT_IN_PATTERNS` and can
  be extended via ``IDP Extraction Template.page_pre_pass_patterns``
  (a JSON list of regex strings) without touching code.
* All compiled regexes are cached on first use.  Compilation failure
  on a custom pattern is logged and the offending regex is skipped;
  it never breaks the pre-pass.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from idp.core.logger import get_logger

logger = get_logger("idp.llm.page_prepass")

PAGE_DIVIDER_PREFIX = "--- Page "

# Generic signals every DocType benefits from: dates, money, identifiers.
_GENERIC_PATTERNS: tuple[str, ...] = (
	# Currency-ish amounts: 1,234.50  | 1234.50 | $1,234 | ₹1,234
	r"\b\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,4})\b",
	r"[\$€£₹¥]\s*\d",
	# Bare integer with 4+ digits (totals, qty, ids).
	r"\b\d{4,}\b",
	# Common date forms.
	r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b",
	r"\b\d{4}-\d{2}-\d{2}\b",
	# Month name + day.
	r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}",
	# Identifiers commonly found in invoices / statements.
	r"\bINV[-/_]?\d+",
	r"\bPO[-/_]?\d+",
	r"\bREF[-/_]?\d+",
)

# Per-target-DocType signal sets.  Keys are lowercase DocType names so
# the lookup is case-insensitive.  The "" key holds the fallback.
_BUILT_IN_PATTERNS: dict[str, tuple[str, ...]] = {
	"": _GENERIC_PATTERNS,
	"sales invoice": _GENERIC_PATTERNS
	+ (r"\bGSTIN\b", r"\b[0-9A-Z]{15}\b", r"\bHSN\b"),
	"purchase invoice": _GENERIC_PATTERNS
	+ (r"\bGSTIN\b", r"\b[0-9A-Z]{15}\b", r"\bHSN\b", r"\bSAC\b"),
	"bank transaction": _GENERIC_PATTERNS
	+ (
		r"\bIFSC[ :]",
		r"\bUTR\b",
		r"\b[A-Z]{4}0[0-9A-Z]{6}\b",  # IFSC
		r"\b\d{9,18}\b",  # account number
		r"\b(?:CR|DR|CREDIT|DEBIT|BAL|BALANCE)\b",
	),
	"payment entry": _GENERIC_PATTERNS
	+ (r"\bUTR\b", r"\bIFSC\b", r"\b[A-Z]{4}0[0-9A-Z]{6}\b"),
	"journal entry": _GENERIC_PATTERNS,
}

# Compiled-pattern cache so we don't recompile every render.
_COMPILED_CACHE: dict[tuple[str, ...], list[re.Pattern[str]]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_relevant_pages(
	text: str,
	target_doctype: str | None = None,
	*,
	extra_patterns: Iterable[str] | None = None,
) -> tuple[str, dict]:
	"""Return ``(filtered_text, stats)`` with no-signal pages elided.

	The input ``text`` is expected to use the
	``--- Page N ---`` divider convention written by every IDP
	extractor.  Pages without a recognised signal are replaced with
	``"[page N omitted — no recognised signal]"`` so the LLM still
	knows the page exists (so cross-page references resolve) but
	no longer pays for its text.

	``stats`` is suitable for direct merge into the IDP Document Log
	row:

	* ``pages_total``       — number of pages found in ``text``
	* ``pages_kept``        — number of pages forwarded to the LLM
	* ``pages_omitted``     — number of pages elided
	* ``chars_total``       — total chars in *text*
	* ``chars_after``       — chars after elision (drives the
	  ``attachment_text_chars_sent`` metric on Document Log)

	If ``text`` lacks page dividers entirely, the original string is
	returned unchanged (single-page docs still benefit from caching
	rather than pre-pass).
	"""

	if not text:
		return text, _empty_stats(text)

	patterns = _compile_patterns(target_doctype, extra_patterns)
	if not patterns:
		return text, _empty_stats(text)

	pages = _split_pages(text)
	if not pages:
		return text, _empty_stats(text)

	kept_chunks: list[str] = []
	omitted = 0
	for header, body in pages:
		if header is None:
			# Pre-divider preamble — always keep (nothing to elide).
			if body:
				kept_chunks.append(body)
			continue
		if _has_signal(body, patterns):
			kept_chunks.append(f"{header}\n{body}".rstrip())
		else:
			page_num = _page_number_from_header(header) or "?"
			kept_chunks.append(f"{header}\n[page {page_num} omitted — no recognised signal]")
			omitted += 1

	filtered = "\n\n".join(c for c in kept_chunks if c)
	stats = {
		"pages_total": sum(1 for h, _b in pages if h is not None),
		"pages_kept": sum(1 for h, _b in pages if h is not None) - omitted,
		"pages_omitted": omitted,
		"chars_total": len(text),
		"chars_after": len(filtered),
	}
	return filtered, stats


def load_template_patterns(target_doctype: str | None) -> list[str]:
	"""Return per-template regex patterns from IDP Extraction Template.

	Returns an empty list when Frappe is unavailable (pure-mode tests)
	or the field is empty / malformed.  Never raises.
	"""

	if not target_doctype:
		return []
	try:
		import frappe
	except ImportError:
		return []
	try:
		rows = frappe.get_all(
			"IDP Extraction Template",
			filters={"target_doctype": target_doctype},
			fields=["page_pre_pass_patterns"],
			order_by="modified desc",
			limit=1,
		)
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"page_pre_pass template lookup failed: {exc}")
		return []
	if not rows:
		return []
	raw = rows[0].get("page_pre_pass_patterns")
	if not raw:
		return []
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
	except (TypeError, ValueError):
		logger.debug("page_pre_pass_patterns is not valid JSON; ignoring")
		return []
	if not isinstance(parsed, list):
		return []
	return [str(p) for p in parsed if p]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _compile_patterns(
	target_doctype: str | None,
	extra_patterns: Iterable[str] | None,
) -> list[re.Pattern[str]]:
	key_doctype = (target_doctype or "").strip().lower()
	base = _BUILT_IN_PATTERNS.get(key_doctype) or _BUILT_IN_PATTERNS[""]
	extras: tuple[str, ...] = tuple(p for p in (extra_patterns or []) if p)
	cache_key: tuple[str, ...] = base + extras
	cached = _COMPILED_CACHE.get(cache_key)
	if cached is not None:
		return cached

	compiled: list[re.Pattern[str]] = []
	for pat in cache_key:
		try:
			compiled.append(re.compile(pat, re.IGNORECASE))
		except re.error as exc:
			logger.debug(f"page_pre_pass: skipping invalid regex {pat!r}: {exc}")
	_COMPILED_CACHE[cache_key] = compiled
	return compiled


def _split_pages(text: str) -> list[tuple[str | None, str]]:
	"""Split *text* on ``--- Page N ---`` markers.

	The first element may have ``header=None`` representing any
	pre-divider preamble.
	"""

	lines = text.splitlines()
	pages: list[tuple[str | None, list[str]]] = []
	current_header: str | None = None
	current_body: list[str] = []

	for line in lines:
		if line.startswith(PAGE_DIVIDER_PREFIX) and "---" in line[len(PAGE_DIVIDER_PREFIX):]:
			# Flush the previous page (if any).
			if current_header is not None or current_body:
				pages.append((current_header, current_body))
			current_header = line.rstrip()
			current_body = []
		else:
			current_body.append(line)
	if current_header is not None or current_body:
		pages.append((current_header, current_body))

	# If no header was seen at all, treat the whole input as a single
	# pre-divider chunk (signals no page boundaries to elide on).
	if not any(h is not None for h, _b in pages):
		return []

	return [(h, "\n".join(b).rstrip("\n")) for h, b in pages]


def _has_signal(body: str, patterns: list[re.Pattern[str]]) -> bool:
	if not body or not body.strip():
		return False
	for pat in patterns:
		if pat.search(body):
			return True
	return False


def _page_number_from_header(header: str | None) -> str | None:
	if not header:
		return None
	# Strip the leading prefix and the trailing " ---".
	mid = header[len(PAGE_DIVIDER_PREFIX):]
	# Drop trailing dashes & whitespace.
	mid = mid.rstrip("- ").strip()
	return mid or None


def _empty_stats(text: str) -> dict:
	n = len(text or "")
	return {
		"pages_total": 0,
		"pages_kept": 0,
		"pages_omitted": 0,
		"chars_total": n,
		"chars_after": n,
	}


__all__ = [
	"load_template_patterns",
	"select_relevant_pages",
]
