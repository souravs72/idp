# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Lightweight in-process caches used throughout the IDP pipeline.

Phase 14 focuses on two hot paths:

1. **DocType schemas** — :func:`idp.mappers.base.get_doctype_schema`
   queries ``frappe.get_meta`` and walks every field.  When a user
   extracts multiple invoices in rapid succession, this repeats for
   every request.  :func:`get_doctype_schema_cached` memoises the
   result for a configurable TTL (default 5 minutes).

2. **OCR engine** — the PaddleOCR model is expensive to instantiate.
   The engine is already a module-level singleton, but first-use
   latency is noticeable.  :func:`warm_ocr_engine` exposes a
   one-shot pre-load entry point that ``after_install`` hooks or a
   scheduled warm-up task can invoke.

The cache is intentionally **process-local** (a plain module dict) —
Frappe workers are independent processes so a shared cache offers
little benefit for the typical single-box deployment, and avoiding
Redis round-trips keeps the hot path fast.  Call :func:`clear_all` to
invalidate every cache (used by tests and by the
``clear_idp_caches()`` CLI helper).
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable

from idp.core.logger import get_logger

logger = get_logger("idp.cache")


# ---------------------------------------------------------------------------
# Generic TTL cache primitive
# ---------------------------------------------------------------------------


_DEFAULT_TTL_SECONDS: float = 300.0  # 5 minutes
_lock = Lock()
_store: dict[str, tuple[float, Any]] = {}


def _now() -> float:
	return time.monotonic()


def cache_get(key: str) -> Any | None:
	"""Return the cached value for *key* or ``None`` if missing/expired."""
	with _lock:
		entry = _store.get(key)
	if entry is None:
		return None
	expiry, value = entry
	if _now() >= expiry:
		# Expired — evict eagerly to keep the store tidy.
		with _lock:
			_store.pop(key, None)
		return None
	return value


def cache_set(key: str, value: Any, ttl_seconds: float | None = None) -> None:
	"""Store *value* under *key* with a ``ttl_seconds`` lifetime."""
	ttl = _DEFAULT_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
	with _lock:
		_store[key] = (_now() + ttl, value)


def cache_delete(key: str) -> bool:
	"""Evict *key*.  Returns True if something was removed."""
	with _lock:
		return _store.pop(key, None) is not None


def clear_all() -> int:
	"""Flush the entire cache.  Returns the number of entries evicted."""
	with _lock:
		count = len(_store)
		_store.clear()
	return count


def memoize(key: str, loader: Callable[[], Any], ttl_seconds: float | None = None) -> Any:
	"""Return ``loader()`` if not cached, otherwise the cached value."""
	hit = cache_get(key)
	if hit is not None:
		return hit
	value = loader()
	cache_set(key, value, ttl_seconds=ttl_seconds)
	return value


# ---------------------------------------------------------------------------
# DocType schema cache
# ---------------------------------------------------------------------------


SCHEMA_TTL_SECONDS: float = 300.0


def get_doctype_schema_cached(doctype: str, ttl_seconds: float | None = None) -> dict:
	"""Return the DocType schema dict, caching by doctype name.

	Wraps :func:`idp.mappers.base.get_doctype_schema` — the first
	call populates the cache; subsequent calls return the cached copy
	until the TTL expires.  On any unexpected error the underlying
	loader is invoked directly so a cache bug never breaks extraction.
	"""
	# Local import avoids a circular dependency at module load time.
	from idp.mappers.base import get_doctype_schema

	key = f"idp:schema:{doctype}"
	ttl = SCHEMA_TTL_SECONDS if ttl_seconds is None else float(ttl_seconds)
	try:
		return memoize(key, lambda: get_doctype_schema(doctype), ttl_seconds=ttl)
	except Exception:
		logger.warning("Schema cache failure — falling back to direct load", exc_info=True)
		return get_doctype_schema(doctype)


# ---------------------------------------------------------------------------
# OCR engine warm-up
# ---------------------------------------------------------------------------


def warm_ocr_engine(lang: str = "en") -> bool:
	"""Pre-instantiate the PaddleOCR model so the first extraction is fast.

	Returns True if the engine was touched, False if unavailable (e.g.
	PaddleOCR is not installed in this environment).  Never raises —
	warm-up is a best-effort optimisation.
	"""
	try:
		from idp.ocr.engine import get_ocr_engine  # noqa: WPS433 (lazy)

		engine = get_ocr_engine(lang=lang)
		logger.info("PaddleOCR warm-up complete for lang=%s", lang)
		return engine is not None
	except Exception as exc:  # pragma: no cover — optional dependency
		logger.info("OCR warm-up skipped: %s", exc)
		return False


# ---------------------------------------------------------------------------
# Introspection (used by tests and the /get_cache_stats debug endpoint)
# ---------------------------------------------------------------------------


def cache_stats() -> dict:
	"""Return (non-secret) diagnostic counters for the in-process cache."""
	with _lock:
		now = _now()
		total = len(_store)
		live = sum(1 for expiry, _v in _store.values() if expiry > now)
	return {"entries": total, "live_entries": live, "default_ttl_seconds": _DEFAULT_TTL_SECONDS}
