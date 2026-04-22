# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.cache` (Phase 14)."""

from __future__ import annotations

import importlib
import time


def _reload_cache(monkeypatch, frappe_stub):  # noqa: ARG001
	import idp.core.cache as cache

	importlib.reload(cache)
	cache.clear_all()
	return cache


def test_set_and_get(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	cache.cache_set("k", "v", ttl_seconds=60)
	assert cache.cache_get("k") == "v"


def test_expired_entry_returns_none(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	cache.cache_set("k", "v", ttl_seconds=0.01)
	time.sleep(0.02)
	assert cache.cache_get("k") is None


def test_delete(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	cache.cache_set("k", "v")
	assert cache.cache_delete("k") is True
	assert cache.cache_delete("k") is False


def test_memoize_only_calls_loader_once(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	calls = []

	def loader():
		calls.append(1)
		return {"loaded": True}

	r1 = cache.memoize("memo-key", loader)
	r2 = cache.memoize("memo-key", loader)
	assert r1 == r2
	assert len(calls) == 1


def test_clear_all_reports_count(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	cache.cache_set("a", 1)
	cache.cache_set("b", 2)
	assert cache.clear_all() == 2
	assert cache.cache_get("a") is None


def test_cache_stats_shape(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	cache.cache_set("live", 1, ttl_seconds=60)
	stats = cache.cache_stats()
	assert stats["entries"] >= 1
	assert stats["live_entries"] >= 1
	assert "default_ttl_seconds" in stats


def test_warm_ocr_engine_never_raises(frappe_stub, monkeypatch):
	cache = _reload_cache(monkeypatch, frappe_stub)
	# In pure mode PaddleOCR is probably unavailable; should still return bool.
	result = cache.warm_ocr_engine()
	assert isinstance(result, bool)
