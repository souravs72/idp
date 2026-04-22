# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.retention` (Phase 14)."""

from __future__ import annotations

import importlib
import time
from pathlib import Path


def _reload_retention(monkeypatch, frappe_stub):  # noqa: ARG001
	import idp.core.retention as retention

	importlib.reload(retention)
	return retention


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def test_defaults_when_settings_missing(frappe_stub, monkeypatch):
	ret = _reload_retention(monkeypatch, frappe_stub)

	def raise_exc(_name):
		raise RuntimeError("no settings")

	monkeypatch.setattr(frappe_stub, "get_cached_doc", raise_exc)
	cfg = ret._get_retention_config()
	assert cfg["log_retention_days"] == 90
	assert cfg["log_prune_after_days"] == 365
	assert cfg["temp_max_age_hours"] == 24


def test_honours_settings_override(frappe_stub, monkeypatch):
	ret = _reload_retention(monkeypatch, frappe_stub)

	class _Settings:
		log_retention_days = 7
		log_prune_after_days = 30
		temp_max_age_hours = 2

	monkeypatch.setattr(frappe_stub, "get_cached_doc", lambda _n: _Settings())
	cfg = ret._get_retention_config()
	assert cfg["log_retention_days"] == 7
	assert cfg["log_prune_after_days"] == 30
	assert cfg["temp_max_age_hours"] == 2


# ---------------------------------------------------------------------------
# archive_stale_logs / prune_old_logs (pure-mode: SQL path is stubbed)
# ---------------------------------------------------------------------------


def test_archive_threshold_zero_is_noop(frappe_stub, monkeypatch):
	ret = _reload_retention(monkeypatch, frappe_stub)
	out = ret.archive_stale_logs(older_than_days=0)
	assert out["archived"] == 0


def test_prune_threshold_zero_is_noop(frappe_stub, monkeypatch):
	ret = _reload_retention(monkeypatch, frappe_stub)
	out = ret.prune_old_logs(older_than_days=0)
	assert out["deleted"] == 0


# ---------------------------------------------------------------------------
# purge_temp_files
# ---------------------------------------------------------------------------


def test_purge_temp_files_deletes_old_only(frappe_stub, monkeypatch, tmp_path):
	ret = _reload_retention(monkeypatch, frappe_stub)

	old = tmp_path / "old.tmp"
	new = tmp_path / "new.tmp"
	old.write_text("old")
	new.write_text("new")

	# Make "old" 25 hours old.
	mtime = time.time() - (25 * 3600)
	import os
	os.utime(old, (mtime, mtime))

	result = ret.purge_temp_files(max_age_hours=24, directory=str(tmp_path))
	assert result["deleted"] == 1
	assert not old.exists()
	assert new.exists()


def test_purge_temp_files_missing_dir_is_noop(frappe_stub, monkeypatch, tmp_path):
	ret = _reload_retention(monkeypatch, frappe_stub)
	missing = tmp_path / "nope"
	out = ret.purge_temp_files(max_age_hours=1, directory=str(missing))
	assert out["deleted"] == 0


def test_purge_temp_files_max_age_zero_noop(frappe_stub, monkeypatch, tmp_path):
	ret = _reload_retention(monkeypatch, frappe_stub)
	(tmp_path / "a.tmp").write_text("x")
	out = ret.purge_temp_files(max_age_hours=0, directory=str(tmp_path))
	assert out["deleted"] == 0


# ---------------------------------------------------------------------------
# daily() entry point
# ---------------------------------------------------------------------------


def test_daily_returns_all_three_sections(frappe_stub, monkeypatch, tmp_path):
	ret = _reload_retention(monkeypatch, frappe_stub)

	# Make temp dir resolve to tmp_path so purge runs without touching site.
	monkeypatch.setattr(ret, "_default_temp_dir", lambda: Path(tmp_path))
	out = ret.daily()
	assert "archived" in out
	assert "pruned" in out
	assert "temp_files" in out
