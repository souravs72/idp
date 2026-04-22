# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.rate_limit` (Phase 14)."""

from __future__ import annotations

import importlib
import time

import pytest


class _FakeCache:
	"""Minimal Redis-compatible stub used by the rate-limit tests."""

	def __init__(self):
		self._store: dict = {}

	def get_value(self, key):
		return self._store.get(key)

	def set_value(self, key, value, expires_in_sec=None):  # noqa: ARG002
		self._store[key] = value

	def delete_value(self, key):
		self._store.pop(key, None)


def _reload_rl(monkeypatch, frappe_stub, cache):  # noqa: ARG001
	# Attach the fake cache to the Frappe stub.
	frappe_stub.cache = lambda: cache
	import idp.core.rate_limit as rl

	importlib.reload(rl)
	return rl


def test_first_call_records_slot(frappe_stub, monkeypatch):
	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	result = rl.check_and_consume(user="alice")
	assert result["user_count"] == 1
	assert result["global_count"] == 1


def test_multiple_calls_accumulate(frappe_stub, monkeypatch):
	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	for _ in range(3):
		rl.check_and_consume(user="alice")
	result = rl.status(user="alice")
	assert result["user_count"] == 3


def test_per_user_limit_raises(frappe_stub, monkeypatch):
	from idp.core.exceptions import RateLimitExceededError

	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	# Force a tiny limit by patching _get_limits for this test.
	monkeypatch.setattr(rl, "_get_limits", lambda: (2, 999))
	rl.check_and_consume(user="bob")
	rl.check_and_consume(user="bob")
	with pytest.raises(RateLimitExceededError) as exc_info:
		rl.check_and_consume(user="bob")
	assert exc_info.value.details["bucket"] == "user"


def test_global_limit_raises(frappe_stub, monkeypatch):
	from idp.core.exceptions import RateLimitExceededError

	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	monkeypatch.setattr(rl, "_get_limits", lambda: (999, 2))
	rl.check_and_consume(user="u1")
	rl.check_and_consume(user="u2")
	with pytest.raises(RateLimitExceededError) as exc_info:
		rl.check_and_consume(user="u3")
	assert exc_info.value.details["bucket"] == "global"


def test_window_expires(frappe_stub, monkeypatch):
	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	# Shrink the window so old entries are dropped almost immediately.
	monkeypatch.setattr(rl, "WINDOW_SECONDS", 0.01)
	monkeypatch.setattr(rl, "_get_limits", lambda: (1, 999))
	rl.check_and_consume(user="eve")
	time.sleep(0.02)
	# Old entry should be pruned, allowing a fresh call.
	rl.check_and_consume(user="eve")


def test_reset_clears_user_bucket(frappe_stub, monkeypatch):
	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	rl.check_and_consume(user="carol")
	assert rl.status(user="carol")["user_count"] == 1
	rl.reset(user="carol")
	assert rl.status(user="carol")["user_count"] == 0


def test_status_does_not_consume(frappe_stub, monkeypatch):
	cache = _FakeCache()
	rl = _reload_rl(monkeypatch, frappe_stub, cache)
	rl.check_and_consume(user="dan")
	for _ in range(5):
		rl.status(user="dan")
	# Still only one recorded request.
	assert rl.status(user="dan")["user_count"] == 1


def test_fails_open_when_cache_unavailable(frappe_stub, monkeypatch):
	# Simulate cache returning None (unreachable Redis).
	frappe_stub.cache = lambda: None
	import idp.core.rate_limit as rl

	importlib.reload(rl)
	# Should not raise — limiter fails open.
	result = rl.check_and_consume(user="z")
	assert "user_count" in result
