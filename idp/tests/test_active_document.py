# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Tests for the active-document context injected into the chat system prompt.

Pure-mode: no Frappe site required.  We stub ``frappe.db`` and
``frappe.get_meta`` to exercise the read / write paths in
:mod:`idp.llm.active_document` and the stamping branch in
:mod:`idp.tools.registry`.
"""

from __future__ import annotations

import sys
import types

import pytest

from idp.tools.base import ToolContext, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_frappe_stub(monkeypatch, *, conversation_row=None, doc_fields=None, exists=True):
	"""Install a minimal ``frappe`` module with the surface we touch.

	``conversation_row`` is what ``frappe.db.get_value("IDP Conversation", ...)``
	returns; ``doc_fields`` is what ``frappe.db.get_value(<doctype>, <name>, [...])``
	returns; ``exists`` controls ``frappe.db.exists``.
	"""

	mod = types.ModuleType("frappe")
	writes: list[tuple[str, str, dict]] = []
	mod._writes = writes  # exposed for assertions

	class _DB:
		def get_value(self_inner, doctype, name, fields, as_dict=False):  # noqa: ARG002
			if doctype == "IDP Conversation":
				return dict(conversation_row) if conversation_row else None
			if doc_fields is None:
				return None
			# Honour the requested field list, the way real Frappe does.
			if isinstance(fields, (list, tuple)):
				picked = {k: doc_fields.get(k) for k in fields}
			else:
				picked = {fields: doc_fields.get(fields)}
			return dict(picked) if as_dict else picked

		def set_value(self_inner, doctype, name, values, update_modified=True):  # noqa: ARG002
			writes.append((doctype, name, dict(values)))

		def exists(self_inner, _doctype, _name):
			return exists

	class _Meta:
		def __init__(self, fields):
			self.fields = [types.SimpleNamespace(fieldname=f) for f in fields]

	def get_meta(_doctype):
		return _Meta(list((doc_fields or {}).keys()))

	mod.db = _DB()
	mod.get_meta = get_meta
	monkeypatch.setitem(sys.modules, "frappe", mod)
	return mod


# ---------------------------------------------------------------------------
# set_active_document / get_active_document
# ---------------------------------------------------------------------------


def test_set_active_document_writes_when_changed(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": "Purchase Invoice",
			"active_document_name": "PI-OLD",
		},
	)

	from idp.llm.active_document import set_active_document

	set_active_document("IDPCONV-2026-0001", "Purchase Invoice", "PI-NEW")

	assert stub._writes == [
		(
			"IDP Conversation",
			"IDPCONV-2026-0001",
			{
				"active_document_doctype": "Purchase Invoice",
				"active_document_name": "PI-NEW",
			},
		)
	]


def test_set_active_document_is_noop_when_already_matches(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": "Purchase Invoice",
			"active_document_name": "PI-001",
		},
	)

	from idp.llm.active_document import set_active_document

	set_active_document("IDPCONV-2026-0001", "Purchase Invoice", "PI-001")

	assert stub._writes == []


def test_set_active_document_rejects_empty_arguments(monkeypatch):
	stub = _install_frappe_stub(monkeypatch)
	from idp.llm.active_document import set_active_document

	set_active_document("", "Purchase Invoice", "PI-001")
	set_active_document("IDPCONV-2026-0001", "", "PI-001")
	set_active_document("IDPCONV-2026-0001", "Purchase Invoice", "")

	assert stub._writes == []


def test_get_active_document_returns_none_when_unset(monkeypatch):
	_install_frappe_stub(
		monkeypatch,
		conversation_row={"active_document_doctype": None, "active_document_name": None},
	)
	from idp.llm.active_document import get_active_document

	assert get_active_document("IDPCONV-2026-0001") is None


def test_get_active_document_returns_none_when_doc_missing(monkeypatch):
	_install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": "Purchase Invoice",
			"active_document_name": "PI-GONE",
		},
		exists=False,
	)
	from idp.llm.active_document import get_active_document

	assert get_active_document("IDPCONV-2026-0001") is None


def test_get_active_document_filters_to_present_interesting_fields(monkeypatch):
	_install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": "Purchase Invoice",
			"active_document_name": "PI-001",
		},
		doc_fields={
			"company": "Tara Technologies",
			"supplier": "Wind Power LLC",
			"posting_date": "2026-04-01",
			"grand_total": 1500.0,
			"bill_no": None,  # None is pruned
			"reference_no": "",  # empty string is pruned
			"custom_unrelated": "ignored",  # not in _INTERESTING_FIELDS
		},
	)
	from idp.llm.active_document import get_active_document

	out = get_active_document("IDPCONV-2026-0001")

	assert out is not None
	assert out["doctype"] == "Purchase Invoice"
	assert out["name"] == "PI-001"
	# Only interesting fields with meaningful values survive the filter.
	assert out["fields"] == {
		"company": "Tara Technologies",
		"supplier": "Wind Power LLC",
		"posting_date": "2026-04-01",
		"grand_total": 1500.0,
	}


# ---------------------------------------------------------------------------
# render_context_block
# ---------------------------------------------------------------------------


def test_render_context_block_returns_empty_when_missing():
	from idp.llm.active_document import render_context_block

	assert render_context_block(None) == ""
	assert render_context_block({"doctype": "", "name": "X"}) == ""
	assert render_context_block({"doctype": "X", "name": ""}) == ""


def test_render_context_block_includes_identity_and_fields():
	from idp.llm.active_document import render_context_block

	out = render_context_block(
		{
			"doctype": "Purchase Invoice",
			"name": "PI-001",
			"fields": {"company": "Tara Technologies", "supplier": "Wind Power LLC"},
		}
	)

	assert 'Purchase Invoice "PI-001"' in out
	assert "company: Tara Technologies" in out
	assert "supplier: Wind Power LLC" in out
	# Behavioural nudge for the LLM is present.
	assert "update_document" in out


# ---------------------------------------------------------------------------
# build_chat_system_prompt integration
# ---------------------------------------------------------------------------


def test_build_chat_system_prompt_appends_active_document_block(monkeypatch):
	# No Frappe access — render_context_block runs purely from the dict.
	from idp.llm.prompts import build_chat_system_prompt

	with_active = build_chat_system_prompt(
		target_doctype="Purchase Invoice",
		company="Tara Technologies",
		active_document={
			"doctype": "Purchase Invoice",
			"name": "PI-001",
			"fields": {"company": "Tara Technologies", "supplier": "Wind Power LLC"},
		},
	)
	without_active = build_chat_system_prompt(
		target_doctype="Purchase Invoice",
		company="Tara Technologies",
	)

	assert 'Active document: Purchase Invoice "PI-001"' in with_active
	assert "Active document" not in without_active


# ---------------------------------------------------------------------------
# Tool dispatch stamping
# ---------------------------------------------------------------------------


def test_maybe_stamp_active_document_writes_from_update_args(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": None,
			"active_document_name": None,
		},
	)

	from idp.tools.registry import _maybe_stamp_active_document

	ctx = ToolContext(conversation_id="IDPCONV-1", user="u@example.com")
	_maybe_stamp_active_document(
		"update_document",
		{"doctype": "Purchase Invoice", "name": "PI-001", "updates": {}},
		ToolResult.ok(),
		ctx,
	)

	assert stub._writes and stub._writes[-1][2] == {
		"active_document_doctype": "Purchase Invoice",
		"active_document_name": "PI-001",
	}


def test_maybe_stamp_active_document_uses_create_result(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": None,
			"active_document_name": None,
		},
	)
	from idp.tools.registry import _maybe_stamp_active_document

	ctx = ToolContext(conversation_id="IDPCONV-1", user="u@example.com")
	_maybe_stamp_active_document(
		"create_document",
		{"doctype": "Purchase Invoice"},
		ToolResult.ok({"doctype": "Purchase Invoice", "name": "ACC-PINV-2026-001"}),
		ctx,
	)

	assert stub._writes and stub._writes[-1][2] == {
		"active_document_doctype": "Purchase Invoice",
		"active_document_name": "ACC-PINV-2026-001",
	}


def test_maybe_stamp_active_document_clears_on_matching_delete(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={
			"active_document_doctype": "Purchase Invoice",
			"active_document_name": "PI-001",
		},
	)
	from idp.tools.registry import _maybe_stamp_active_document

	ctx = ToolContext(conversation_id="IDPCONV-1", user="u@example.com")
	_maybe_stamp_active_document(
		"delete_document",
		{"doctype": "Purchase Invoice", "name": "PI-001", "confirm": True},
		ToolResult.ok(),
		ctx,
	)

	assert stub._writes and stub._writes[-1][2] == {
		"active_document_doctype": None,
		"active_document_name": None,
	}


def test_maybe_stamp_active_document_skips_unrelated_tool(monkeypatch):
	stub = _install_frappe_stub(
		monkeypatch,
		conversation_row={"active_document_doctype": None, "active_document_name": None},
	)
	from idp.tools.registry import _maybe_stamp_active_document

	ctx = ToolContext(conversation_id="IDPCONV-1", user="u@example.com")
	_maybe_stamp_active_document(
		"search_documents",
		{"doctype": "Purchase Invoice", "filters": {}},
		ToolResult.ok({"rows": []}),
		ctx,
	)

	assert stub._writes == []
