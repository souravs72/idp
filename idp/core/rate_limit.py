# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Per-user and global rate limiting for the IDP APIs (Phase 14).

The implementation uses a **sliding-window counter** backed by a
Frappe cache (Redis via ``frappe.cache()``).  When the site's cache is
unreachable the limiter *fails open* — it logs a warning and allows
the request rather than blocking legitimate work.

Two independent buckets are maintained:

* ``idp:ratelimit:user:{user}`` — per-user window.
* ``idp:ratelimit:global`` — system-wide window.

Defaults match the roadmap (§14.4):

* ``default_user_limit``   : 50 requests / hour
* ``default_global_limit`` : 500 requests / hour

Limits can be overridden via IDP Settings fields
``rate_limit_user_per_hour`` / ``rate_limit_global_per_hour`` when
they exist; otherwise the roadmap defaults apply.
"""

from __future__ import annotations

import time

import frappe

from idp.core.exceptions import RateLimitExceededError
from idp.core.logger import get_logger

logger = get_logger("idp.ratelimit")


DEFAULT_USER_LIMIT_PER_HOUR = 50
DEFAULT_GLOBAL_LIMIT_PER_HOUR = 500
WINDOW_SECONDS = 3600


# ---------------------------------------------------------------------------
# Settings lookup
# ---------------------------------------------------------------------------


def _get_limits() -> tuple[int, int]:
	"""Return ``(user_limit, global_limit)``, honouring IDP Settings overrides."""
	try:
		settings = frappe.get_cached_doc("IDP Settings")
	except Exception:
		return DEFAULT_USER_LIMIT_PER_HOUR, DEFAULT_GLOBAL_LIMIT_PER_HOUR

	user_limit = getattr(settings, "rate_limit_user_per_hour", None)
	global_limit = getattr(settings, "rate_limit_global_per_hour", None)
	return (
		int(user_limit) if user_limit else DEFAULT_USER_LIMIT_PER_HOUR,
		int(global_limit) if global_limit else DEFAULT_GLOBAL_LIMIT_PER_HOUR,
	)


# ---------------------------------------------------------------------------
# Sliding window store
# ---------------------------------------------------------------------------


def _cache():
	"""Return the Frappe cache backend (Redis in production)."""
	try:
		return frappe.cache()
	except Exception:
		return None


def _prune_and_count(key: str, now: float) -> list[float]:
	"""Load and prune the timestamp list for *key*, returning the live entries."""
	store = _cache()
	if store is None:
		return []

	try:
		raw = store.get_value(key) or []
		if not isinstance(raw, list):
			raw = []
		# Drop entries older than the window
		cutoff = now - WINDOW_SECONDS
		kept = [ts for ts in raw if isinstance(ts, (int, float)) and ts >= cutoff]
		return kept
	except Exception:
		logger.warning("Rate-limit cache read failed for %s", key, exc_info=True)
		return []


def _store_window(key: str, timestamps: list[float]) -> None:
	store = _cache()
	if store is None:
		return
	try:
		store.set_value(key, timestamps, expires_in_sec=WINDOW_SECONDS + 60)
	except Exception:
		logger.warning("Rate-limit cache write failed for %s", key, exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_and_consume(user: str | None = None) -> dict:
	"""Record a request under the user + global buckets.

	Raises :class:`RateLimitExceededError` if either bucket is full.
	Returns a diagnostic dict describing the two buckets.
	"""
	user = user or getattr(frappe.session, "user", "Guest")
	user_limit, global_limit = _get_limits()
	now = time.time()

	user_key = f"idp:ratelimit:user:{user}"
	global_key = "idp:ratelimit:global"

	# --- Per-user bucket ---
	user_window = _prune_and_count(user_key, now)
	if len(user_window) >= user_limit:
		raise RateLimitExceededError(
			f"Per-user rate limit exceeded ({user_limit}/hour).",
			details={
				"bucket": "user",
				"user": user,
				"limit": user_limit,
				"window_seconds": WINDOW_SECONDS,
				"current_count": len(user_window),
			},
		)

	# --- Global bucket ---
	global_window = _prune_and_count(global_key, now)
	if len(global_window) >= global_limit:
		raise RateLimitExceededError(
			f"Global rate limit exceeded ({global_limit}/hour).",
			details={
				"bucket": "global",
				"limit": global_limit,
				"window_seconds": WINDOW_SECONDS,
				"current_count": len(global_window),
			},
		)

	# Both buckets have headroom — record the request.
	user_window.append(now)
	global_window.append(now)
	_store_window(user_key, user_window)
	_store_window(global_key, global_window)

	return {
		"user": user,
		"user_count": len(user_window),
		"user_limit": user_limit,
		"global_count": len(global_window),
		"global_limit": global_limit,
		"window_seconds": WINDOW_SECONDS,
	}


def status(user: str | None = None) -> dict:
	"""Return current bucket occupancy without consuming a slot."""
	user = user or getattr(frappe.session, "user", "Guest")
	user_limit, global_limit = _get_limits()
	now = time.time()
	return {
		"user": user,
		"user_count": len(_prune_and_count(f"idp:ratelimit:user:{user}", now)),
		"user_limit": user_limit,
		"global_count": len(_prune_and_count("idp:ratelimit:global", now)),
		"global_limit": global_limit,
		"window_seconds": WINDOW_SECONDS,
	}


def check_and_consume_tool(
	tool_name: str,
	*,
	user: str | None = None,
	limit_per_hour: int,
) -> dict:
	"""Per-tool, per-user sliding-window check.

	Independent of the global IDP buckets — destructive tools
	(``update_document``, ``delete_document``) carry their own caps and
	should not eat the user's general budget.  Bucket key:
	``idp:ratelimit:tool:{tool_name}:{user}``.

	Raises :class:`RateLimitExceededError` when the bucket is full.
	"""
	user = user or getattr(frappe.session, "user", "Guest")
	now = time.time()
	key = f"idp:ratelimit:tool:{tool_name}:{user}"
	window = _prune_and_count(key, now)
	if len(window) >= limit_per_hour:
		raise RateLimitExceededError(
			f"Per-tool rate limit exceeded for {tool_name!r} ({limit_per_hour}/hour).",
			details={
				"bucket": "tool",
				"tool": tool_name,
				"user": user,
				"limit": limit_per_hour,
				"window_seconds": WINDOW_SECONDS,
				"current_count": len(window),
			},
		)
	window.append(now)
	_store_window(key, window)
	return {
		"tool": tool_name,
		"user": user,
		"count": len(window),
		"limit": limit_per_hour,
		"window_seconds": WINDOW_SECONDS,
	}


def reset(user: str | None = None) -> int:
	"""Clear a user's bucket (and the global bucket if user is ``None``).

	Returns the number of cache keys cleared (0, 1, or 2).
	"""
	store = _cache()
	if store is None:
		return 0
	cleared = 0
	try:
		if user:
			store.delete_value(f"idp:ratelimit:user:{user}")
			cleared += 1
		else:
			store.delete_value("idp:ratelimit:global")
			cleared += 1
	except Exception:
		logger.warning("Rate-limit reset failed", exc_info=True)
	return cleared
