# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Shared pytest fixtures for the IDP test suite.

The test suite is designed to be runnable in two modes:

1. **Bench mode** — inside a Frappe bench with a test site.  Frappe
   framework fixtures (``frappe.db``, ``frappe.get_doc``) are available.
   This is the primary path.

2. **Pure mode** — for fast, framework-light unit tests
   (``test_bank_statement.py`` helpers, audit serialiser, metrics
   percentile math).  These tests monkey-patch the minimal Frappe
   surface they need.

The fixtures below provide reusable scaffolding for both modes so
individual test modules stay focused on behaviour.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Frappe stub for pure-mode tests
# ---------------------------------------------------------------------------


@pytest.fixture
def frappe_stub(monkeypatch):
	"""Provide a minimal ``frappe`` stub for tests that do not need a site.

	The stub records inserts/commits so tests can assert on audit
	behaviour without a real database.
	"""
	mod = types.ModuleType("frappe")

	class _Session:
		user = "test@example.com"

	class _DB:
		def __init__(self):
			self.committed = 0

		def commit(self):
			self.committed += 1

	records: list[dict] = []

	class _Doc(dict):
		def __init__(self, data):
			super().__init__(data)
			self.name = data.get("name") or f"IDPLOG-{len(records) + 1:04d}"

		def insert(self, ignore_permissions=False):  # noqa: ARG002
			records.append(dict(self))
			return self

	def get_doc(data):
		return _Doc(data)

	def get_cached_doc(_name):
		# Default: audit flag absent -> enabled.
		obj = types.SimpleNamespace()
		return obj

	def get_all(_doctype, filters=None, fields=None, order_by=None, limit=0):  # noqa: ARG001
		return list(records)

	mod.session = _Session()
	mod.db = _DB()
	mod.get_doc = get_doc
	mod.get_cached_doc = get_cached_doc
	mod.get_all = get_all

	def whitelist(*_args, **_kwargs):
		def _wrap(fn):
			return fn

		return _wrap

	mod.whitelist = whitelist
	mod.logger = lambda *_a, **_kw: MagicMock()
	mod.throw = lambda msg, *_a, **_kw: (_ for _ in ()).throw(ValueError(msg))
	mod.ValidationError = ValueError
	mod._records = records  # expose for assertions

	# utils submodule needed by metrics._window_filter
	utils_mod = types.ModuleType("frappe.utils")
	from datetime import datetime, timedelta

	def add_to_date(dt, hours=0, **_kw):
		return dt + timedelta(hours=hours)

	def now_datetime():
		return datetime(2026, 4, 22, 12, 0, 0)

	utils_mod.add_to_date = add_to_date
	utils_mod.now_datetime = now_datetime

	monkeypatch.setitem(sys.modules, "frappe", mod)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils_mod)
	return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _pushed_sys_path(path):
	sys.path.insert(0, path)
	try:
		yield
	finally:
		try:
			sys.path.remove(path)
		except ValueError:
			pass


@pytest.fixture
def sample_transactions():
	"""Return a deterministic list of ``BankTransaction`` dicts."""
	return [
		{
			"date": "2026-04-01",
			"description": "Opening transfer",
			"debit": None,
			"credit": 1000.00,
			"balance": 1000.00,
			"reference": "UTR001",
			"row_index": 0,
		},
		{
			"date": "2026-04-02",
			"description": "Payment to ACME",
			"debit": 250.00,
			"credit": None,
			"balance": 750.00,
			"reference": "CHQ-901",
			"row_index": 1,
		},
		{
			"date": "2026-04-03",
			"description": "Salary",
			"debit": None,
			"credit": 5000.00,
			"balance": 5750.00,
			"reference": None,
			"row_index": 2,
		},
	]
