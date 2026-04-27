# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 22 — LLM-backed translator with Frappe cache.

Used to render extracted *narrative* fields (remarks, terms,
descriptions) in the user's chosen output language without ever
translating identifiers, amounts, dates, or item codes.

Design choices
--------------
* **LLM-only.**  We don't ship a deterministic translation table — the
  whole point of Phase 22 is to use the configured LLM for naturalness.
  When the LLM is unreachable we fall back to the original text and
  attach a warning, never raise.
* **Same provider as the hybrid mapper.**  Translation reuses
  :class:`~idp.idp.llm.client.LLMClient.from_settings` so a site running
  the rule mapper only (no API key) silently no-ops.
* **Per-(text, source, target) cache** — keyed on a SHA-256 hash so
  we never log raw text into the cache key.  The cache lives in
  ``frappe.cache()`` when available (Redis on a real bench, in-memory
  on dev/test).  A process-local fallback dict is used when Frappe
  isn't installed (CLI / unit tests).
* **Identifier guard.**  Numeric fields, ISO dates, IBAN/UTR codes, and
  short pure-digit strings are *never* sent to the LLM — we return them
  unchanged.

Public API
----------
* :func:`translate_text` — single string translator.
* :func:`translate_mapping` — translate selected fields of a
  ``MappedDocument``-style header dict in place.  Used by the hybrid
  mapper and the API ``hybrid_map`` endpoint.
* :func:`should_translate_field` — predicate the mapper uses to decide
  whether a field is a "narrative" candidate (versus a date / amount /
  identifier that must stay verbatim).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from idp.core.exceptions import LLMError
from idp.core.logger import get_logger
from idp.idp.mappers.keywords_ml import normalize_language

logger = get_logger("idp.llm.translation")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Cache TTL — translations of the same string almost never change for
# the lifetime of a document, but we still bound it so a site that
# corrects a translation manually doesn't get stuck on the old answer
# forever.
CACHE_TTL_SECONDS: int = 7 * 24 * 60 * 60  # 1 week
CACHE_NAMESPACE: str = "idp:translation"

# Maximum characters we'll send through the LLM in a single call.
# Above this we fall back to the original to avoid runaway cost on
# a stray multi-page contract that ended up in remarks.
MAX_TRANSLATION_CHARS: int = 4_000

# Default narrative fields — checked by ``should_translate_field`` and
# consumed by ``translate_mapping`` when the caller doesn't supply an
# explicit list.
DEFAULT_NARRATIVE_FIELDS: tuple[str, ...] = (
	"remarks",
	"narration",
	"description",
	"terms",
	"terms_and_conditions",
	"comments",
	"notes",
	"memo",
	"shipping_remarks",
	"reason",
)

# Fields that should NEVER be translated — amounts, dates, identifiers.
_NEVER_TRANSLATE_FIELDS: frozenset[str] = frozenset(
	{
		"posting_date",
		"due_date",
		"transaction_date",
		"valid_till",
		"delivery_date",
		"schedule_date",
		"reference_date",
		"cheque_date",
		"bill_no",
		"invoice_no",
		"po_no",
		"quotation_number",
		"reference_no",
		"cheque_no",
		"check_no",
		"utr",
		"net_total",
		"grand_total",
		"paid_amount",
		"total_debit",
		"total_credit",
		"taxes_and_charges",
		"opportunity_amount",
		"currency",
		"item_code",
		"hsn_code",
		"sac_code",
		"gstin",
		"pan",
		"tax_id",
	}
)

# Process-local fallback cache when frappe.cache() is unavailable
# (e.g. running the test suite without a bench).  Bounded so it doesn't
# leak in long-running processes.
_LOCAL_CACHE: dict[str, str] = {}
_LOCAL_CACHE_MAX = 2_048


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def should_translate_field(
	fieldname: str,
	*,
	extra_narrative: Iterable[str] | None = None,
) -> bool:
	"""Return ``True`` when *fieldname* is a translation candidate.

	The default list covers ERPNext's most common narrative fields.
	Callers can extend with *extra_narrative* (e.g. industry-specific
	prompt-library fields) without rebuilding the constant.
	"""

	if not fieldname:
		return False
	fn = fieldname.strip().lower()
	if fn in _NEVER_TRANSLATE_FIELDS:
		return False
	if fn in DEFAULT_NARRATIVE_FIELDS:
		return True
	if extra_narrative and fn in {f.strip().lower() for f in extra_narrative if f}:
		return True
	return False


def translate_text(
	text: str,
	*,
	source_lang: str,
	target_lang: str,
	llm_client: Any | None = None,
	use_cache: bool = True,
) -> tuple[str, bool]:
	"""Translate *text* from ``source_lang`` to ``target_lang``.

	Returns a ``(translated_text, was_translated)`` tuple.
	``was_translated`` is ``False`` whenever the function short-circuited
	(same language, empty text, identifier, LLM unavailable, cache miss
	+ no client).  Callers can use the flag to attach provenance to the
	mapped field without re-running the LLM.
	"""

	if not text or not isinstance(text, str):
		return text or "", False

	src = normalize_language(source_lang)
	tgt = normalize_language(target_lang)
	if src == tgt:
		return text, False

	stripped = text.strip()
	if not stripped:
		return text, False

	if _looks_like_identifier(stripped):
		return text, False

	if len(stripped) > MAX_TRANSLATION_CHARS:
		logger.debug(f"translation skipped: text exceeds {MAX_TRANSLATION_CHARS} chars")
		return text, False

	cache_key = _build_cache_key(stripped, src, tgt)
	if use_cache:
		cached = _cache_get(cache_key)
		if cached is not None:
			return cached, True

	client = llm_client or _build_default_client()
	if client is None:
		# No LLM configured — graceful no-op so rule-only sites keep
		# working with the original-language text.
		return text, False

	try:
		translated = _call_llm(client, stripped, src, tgt)
	except LLMError as exc:
		logger.warning(f"translation failed via LLM ({src} → {tgt}): {exc}")
		return text, False
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"translation aborted: {exc}")
		return text, False

	if not translated:
		return text, False

	# Preserve any leading/trailing whitespace from the original so the
	# mapper's downstream concatenation doesn't drift.
	translated = _restore_whitespace(text, translated)
	if use_cache:
		_cache_set(cache_key, translated)
	return translated, True


def translate_mapping(
	header: dict,
	*,
	source_lang: str,
	target_lang: str,
	fields: Iterable[str] | None = None,
	llm_client: Any | None = None,
) -> dict[str, dict]:
	"""Translate the narrative fields of *header* in place.

	Returns ``{fieldname: {"original": str, "translated": str}}`` for
	every field that was actually translated, so callers can record the
	swap in :attr:`MappedDocument.warnings` or in conversation history.
	"""

	if not header:
		return {}
	src = normalize_language(source_lang)
	tgt = normalize_language(target_lang)
	if src == tgt:
		return {}

	candidates = list(fields) if fields else list(DEFAULT_NARRATIVE_FIELDS)
	swaps: dict[str, dict] = {}
	for fn in candidates:
		raw = header.get(fn)
		if not isinstance(raw, str) or not raw.strip():
			continue
		if not should_translate_field(fn, extra_narrative=candidates):
			continue
		translated, ok = translate_text(
			raw,
			source_lang=src,
			target_lang=tgt,
			llm_client=llm_client,
		)
		if ok and translated != raw:
			swaps[fn] = {"original": raw, "translated": translated}
			header[fn] = translated
	return swaps


# ---------------------------------------------------------------------------
# Internals — kept module-private so callers can't accidentally cache
# strings outside the dedicated helpers.
# ---------------------------------------------------------------------------


_IDENTIFIER_RE = re.compile(
	r"""^(
		\d+(\.\d+)?            # plain number
		| [A-Z]{2,5}-?\d+([-/]\d+)*  # invoice-style codes (INV-2026-0001)
		| \d{4}-\d{1,2}-\d{1,2}     # ISO dates
		| \d{1,2}/\d{1,2}/\d{2,4}   # slash dates
		| \d{1,2}-\d{1,2}-\d{2,4}   # dash dates
		| [+]?\d[\d\s\-()]{6,}      # phone-like numbers
		| \w+@\w+\.\w+              # email
		| [A-Z]{2}\d{2}[A-Z0-9]{6,32}  # IBAN-ish
	)$""",
	re.VERBOSE,
)


def _looks_like_identifier(text: str) -> bool:
	"""Heuristic guard against translating amounts / dates / codes."""

	if len(text) <= 2:
		return True
	# Pure digits, even with separators and currency symbols.
	if all(ch in "0123456789.,- $€£₹¥" for ch in text):
		return True
	if _IDENTIFIER_RE.match(text):
		return True
	return False


def _build_cache_key(text: str, source: str, target: str) -> str:
	digest = hashlib.sha256(f"{source}|{target}|{text}".encode()).hexdigest()
	return f"{CACHE_NAMESPACE}:{digest}"


def _cache_get(key: str) -> str | None:
	try:
		import frappe

		cache = frappe.cache()
		val = cache.get_value(key)
		if val is None:
			return None
		# Frappe stores bytes for strings via Redis on real benches.
		if isinstance(val, bytes):
			try:
				return val.decode("utf-8")
			except UnicodeDecodeError:
				return None
		return str(val)
	except Exception:
		return _LOCAL_CACHE.get(key)


def _cache_set(key: str, value: str) -> None:
	try:
		import frappe

		cache = frappe.cache()
		cache.set_value(key, value, expires_in_sec=CACHE_TTL_SECONDS)
		return
	except Exception:
		pass
	# Fallback: bounded process-local dict.
	if len(_LOCAL_CACHE) >= _LOCAL_CACHE_MAX:
		# Evict an arbitrary entry — translation cache pressure is rare
		# and we don't need an LRU here.
		try:
			_LOCAL_CACHE.pop(next(iter(_LOCAL_CACHE)))
		except StopIteration:
			pass
	_LOCAL_CACHE[key] = value


def _build_default_client() -> Any | None:
	try:
		from idp.idp.llm.client import LLMClient

		return LLMClient.from_settings()
	except Exception as exc:
		logger.debug(f"translation: no default LLM client available ({exc})")
		return None


def _call_llm(client: Any, text: str, src: str, tgt: str) -> str:
	"""Run a one-shot translation prompt against *client*.

	Kept tiny — no tool calls, no JSON mode, no system-prompt library
	lookup.  Accuracy here is dominated by the model itself, not the
	prompt: a verbose prompt costs more without measurable gain.
	"""

	system = (
		"You are a precise document translator.  Translate the user's "
		f"text from {src!r} to {tgt!r}.  Preserve numbers, dates, codes, "
		"named entities, currency symbols, and product/SKU strings "
		"verbatim.  Output ONLY the translation — no quotes, no notes, "
		"no preface."
	)
	response = client.chat(
		messages=[
			{"role": "system", "content": system},
			{"role": "user", "content": text},
		],
		temperature=0.0,
		max_tokens=min(2_048, max(64, len(text) * 4)),
	)
	if response and getattr(response, "content", None):
		out = response.content.strip()
		# Some providers wrap the answer in quotes; strip a single layer.
		if len(out) >= 2 and out[0] == out[-1] and out[0] in ("'", '"'):
			out = out[1:-1].strip()
		return out
	return ""


def _restore_whitespace(original: str, translated: str) -> str:
	"""Re-attach the original's leading / trailing whitespace."""

	leading_len = len(original) - len(original.lstrip())
	trailing_len = len(original) - len(original.rstrip())
	leading = original[:leading_len]
	trailing = original[len(original) - trailing_len :] if trailing_len else ""
	return f"{leading}{translated.strip()}{trailing}"


__all__ = [
	"CACHE_TTL_SECONDS",
	"DEFAULT_NARRATIVE_FIELDS",
	"MAX_TRANSLATION_CHARS",
	"should_translate_field",
	"translate_mapping",
	"translate_text",
]
