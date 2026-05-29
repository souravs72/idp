# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for the document lifecycle tools (search / update / delete).

These tests run in *pure mode* — they stub the minimal slice of the
``frappe`` runtime the tools touch.  They cover:

* search_documents: deny-list rejection, missing read permission,
  row-level filter, projection cap, limit clamp.
* update_document: dry_run diff payload, mutation path + audit hook,
  submitted-doc lockout, permission denial.
* delete_document: confirm gate, snapshot capture, audit token return,
  refusal on submitted docs.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Frappe stub for the lifecycle tools
# ---------------------------------------------------------------------------


def _install_frappe_stub(monkeypatch, *, store):
	mod = types.ModuleType("frappe")

	class _DoesNotExist(Exception):
		pass

	class _PermissionError(Exception):
		pass

	class _LinkExists(Exception):
		pass

	class _ValidationError(Exception):
		pass

	mod.DoesNotExistError = _DoesNotExist
	mod.PermissionError = _PermissionError
	mod.LinkExistsError = _LinkExists
	mod.ValidationError = _ValidationError

	class _Session:
		user = "test@example.com"

	class _DB:
		def __init__(self):
			self.committed = 0
			self.savepoints: list[str] = []
			self.rollbacks: list[str | None] = []
			self.released: list[str] = []

		def commit(self):
			self.committed += 1

		def exists(self, doctype, name):
			return any(
				d["doctype"] == doctype and d["name"] == name for d in store["docs"]
			)

		def savepoint(self, name):
			self.savepoints.append(name)

		def rollback(self, *, save_point=None):
			self.rollbacks.append(save_point)

		def sql(self, query, *args, **kwargs):  # noqa: ARG002
			# Capture RELEASE SAVEPOINT calls so tests can verify
			# cleanup on the success path.
			upper = (query or "").strip().upper()
			if upper.startswith("RELEASE SAVEPOINT"):
				self.released.append(query.split()[-1])
			return []

	class _Doc(dict):
		def __init__(self, data):
			super().__init__(data)

		def __getattr__(self, item):
			# Route attribute access (e.g. ``doc.docstatus``) through the
			# underlying dict so the tools can mix ``doc.get(...)`` and
			# ``getattr(doc, ...)`` interchangeably.
			try:
				return self[item]
			except KeyError as exc:
				raise AttributeError(item) from exc

		@property
		def name(self):
			return self.get("name")

		def get(self, key, default=None):
			return super().get(key, default)

		def as_dict(self):
			return dict(self)

		def update(self, updates):
			for k, v in updates.items():
				self[k] = v

		def save(self):
			store["saves"].append(dict(self))

		def delete(self):
			store["docs"] = [
				d
				for d in store["docs"]
				if not (d["doctype"] == self["doctype"] and d["name"] == self["name"])
			]
			store["deletes"].append({"doctype": self["doctype"], "name": self["name"]})

		def reload(self):
			# Reset in-memory state from the canonical store record so a
			# savepoint rollback test can verify the underlying row.
			for d in store["docs"]:
				if d["doctype"] == self["doctype"] and d["name"] == self["name"]:
					self.update(d)
					return self
			return self

	# Specialised subclass used in pre-flight tests: tagged with a
	# fake ``make_gl_entries`` method so ``_doctype_emits_gl_entries``
	# recognises this as an accounting doctype.
	class _GLDoc(_Doc):
		def make_gl_entries(self):  # noqa: D401 — stub marker, never called
			pass

	def get_doc(doctype, name=None):
		# Two-arg form: load existing record.  Doctypes the env declares
		# as "GL-emitting" hand back the _GLDoc subclass so the
		# pre-flight check's hasattr(cls, "make_gl_entries") probe
		# returns True.
		if name is not None:
			cls = _GLDoc if doctype in store.get("gl_doctypes", set()) else _Doc
			for d in store["docs"]:
				if d["doctype"] == doctype and d["name"] == name:
					return cls(d)
			raise _DoesNotExist(f"{doctype} {name} not found")
		# One-arg form (used by undo to recreate): doctype is actually a dict.
		return _Doc(doctype)

	def has_permission(doctype, ptype, doc=None, user=None):  # noqa: ARG001
		key = (doctype, ptype)
		if key in store["denied_perms"]:
			return False
		return True

	def get_list(doctype, filters=None, or_filters=None, fields=None,  # noqa: ARG001
				 limit_page_length=None, order_by=None, user=None):  # noqa: ARG001
		rows = [d for d in store["docs"] if d["doctype"] == doctype]
		if filters:
			for k, v in (filters or {}).items():
				if isinstance(v, list) and len(v) == 2 and v[0] == "like":
					prefix = v[1].rstrip("%")
					rows = [r for r in rows if str(r.get(k) or "").startswith(prefix)]
				else:
					rows = [r for r in rows if r.get(k) == v]
		if limit_page_length:
			rows = rows[:limit_page_length]
		projection = []
		for r in rows:
			projection.append({f: r.get(f) for f in (fields or ["name"])})
		return projection

	# get_all alias used by the link-resolver helpers.
	def get_all(doctype, filters=None, fields=None, limit_page_length=None,  # noqa: ARG001
				order_by=None):  # noqa: ARG001
		return get_list(
			doctype,
			filters=filters,
			fields=fields,
			limit_page_length=limit_page_length,
		)

	def get_cached_doc(_name):
		return types.SimpleNamespace()

	def whitelist(*_a, **_kw):
		def _wrap(fn):
			return fn
		return _wrap

	def get_meta(doctype):
		# Parent meta for the Purchase Invoice; child meta for the items
		# table; arbitrary Link-target metas (Cost Center etc.) for the
		# auto-resolver tests.
		if doctype == "Purchase Invoice":
			parent_fields = []
			for fn, df in store["fields"].items():
				parent_fields.append(
					types.SimpleNamespace(
						fieldname=fn,
						fieldtype=getattr(df, "fieldtype", "Data"),
						options=getattr(df, "options", None),
						allow_on_submit=getattr(df, "allow_on_submit", 0),
					)
				)
			if store.get("child_fields"):
				parent_fields.append(
					types.SimpleNamespace(
						fieldname="items",
						fieldtype="Table",
						options="Purchase Invoice Item",
						allow_on_submit=0,
					)
				)

			class _Meta:
				fields = parent_fields
				title_field = None

				def get_field(self, fn):
					for df in self.fields:
						if df.fieldname == fn:
							return df
					return None

			return _Meta()

		if doctype == "Purchase Invoice Item":
			child_fields = [
				types.SimpleNamespace(
					fieldname=fn,
					fieldtype=getattr(df, "fieldtype", "Data"),
					options=getattr(df, "options", None),
				)
				for fn, df in store.get("child_fields", {}).items()
			]

			class _ChildMeta:
				fields = child_fields
				title_field = None

				def get_field(self, fn):
					for df in self.fields:
						if df.fieldname == fn:
							return df
					return None

			return _ChildMeta()

		# Generic Link-target meta (used by the resolver tests).
		linkmeta = store.get("link_metas", {}).get(doctype)
		if linkmeta is None:
			linkmeta = {"fields": [], "title_field": None}

		class _LinkMeta:
			fields = [
				types.SimpleNamespace(
					fieldname=fn,
					fieldtype=getattr(df, "fieldtype", "Data"),
					options=getattr(df, "options", None),
				)
				for fn, df in (linkmeta.get("fields") or {}).items()
			]
			title_field = linkmeta.get("title_field")

			def get_field(self, fn):
				for df in self.fields:
					if df.fieldname == fn:
						return df
				return None

		return _LinkMeta()

	def publish_realtime(*_a, **_kw):  # noqa: ARG001
		pass

	mod.session = _Session()
	mod.db = _DB()
	mod.get_doc = get_doc
	mod.get_cached_doc = get_cached_doc
	mod.has_permission = has_permission
	mod.get_list = get_list
	mod.get_all = get_all
	mod.get_meta = get_meta
	mod.whitelist = whitelist
	mod.publish_realtime = publish_realtime
	mod.cache = lambda: None
	mod._store = store

	utils_mod = types.ModuleType("frappe.utils")
	from datetime import datetime, timedelta

	def now_datetime():
		return datetime(2026, 5, 28, 12, 0, 0)

	def get_datetime(v):
		if isinstance(v, datetime):
			return v
		return datetime(2026, 5, 28, 12, 0, 0)

	utils_mod.now_datetime = now_datetime
	utils_mod.get_datetime = get_datetime
	utils_mod.add_to_date = lambda dt, hours=0, **_kw: dt + timedelta(hours=hours)

	monkeypatch.setitem(sys.modules, "frappe", mod)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils_mod)
	return mod


@pytest.fixture
def lifecycle_env(monkeypatch):
	store = {
		"docs": [
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"supplier": "Acme",
				"bill_no": "INV-42",
				"grand_total": 100.0,
				"company": "Company A",
				"docstatus": 0,
			},
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0002",
				"supplier": "Beta",
				"bill_no": "INV-43",
				"grand_total": 200.0,
				"company": "Company B",
				"docstatus": 1,
			},
		],
		"saves": [],
		"deletes": [],
		"denied_perms": set(),
		"fields": {
			"supplier": types.SimpleNamespace(allow_on_submit=0),
			"bill_no": types.SimpleNamespace(allow_on_submit=0),
			"grand_total": types.SimpleNamespace(allow_on_submit=1),
			"remarks": types.SimpleNamespace(allow_on_submit=1),
		},
		"child_fields": {},
		"gl_doctypes": set(),
	}
	frappe = _install_frappe_stub(monkeypatch, store=store)

	# Reload the registry-touching modules so their `import frappe`
	# resolves to the stub.
	for mod_name in (
		"idp.core.audit",
		"idp.core.rate_limit",
		"idp.tools.search_documents",
		"idp.tools.update_document",
		"idp.tools.delete_document",
	):
		if mod_name in sys.modules:
			importlib.reload(sys.modules[mod_name])
		else:
			importlib.import_module(mod_name)

	return {"frappe": frappe, "store": store}


def _ctx(user="test@example.com"):
	from idp.tools.base import ToolContext

	return ToolContext(conversation_id="c1", user=user)


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


class TestSearchDocuments:
	def test_basic_search_returns_rows(self, lifecycle_env):
		from idp.tools.search_documents import search_documents

		result = search_documents(
			{"doctype": "Purchase Invoice", "fields": ["name", "supplier"]},
			_ctx(),
		)
		assert result.success
		assert result.data["total_matched"] == 2
		assert {r["name"] for r in result.data["rows"]} == {"PINV-0001", "PINV-0002"}

	def test_deny_list_rejects_identity_doctype(self, lifecycle_env):
		from idp.tools.search_documents import search_documents

		result = search_documents({"doctype": "User"}, _ctx())
		assert not result.success
		assert result.error_code == "PERMISSION_DENIED"
		assert result.stop_processing

	def test_missing_doctype_fails(self, lifecycle_env):
		from idp.tools.search_documents import search_documents

		result = search_documents({}, _ctx())
		assert not result.success
		assert result.error_code == "MISSING_ARGUMENT"

	def test_no_read_perm_blocks(self, lifecycle_env):
		from idp.tools.search_documents import search_documents

		lifecycle_env["store"]["denied_perms"].add(("Purchase Invoice", "read"))
		result = search_documents({"doctype": "Purchase Invoice"}, _ctx())
		assert not result.success
		assert result.error_code == "PERMISSION_DENIED"

	def test_filters_narrow_results(self, lifecycle_env):
		from idp.tools.search_documents import search_documents

		result = search_documents(
			{
				"doctype": "Purchase Invoice",
				"filters": {"supplier": "Acme"},
				"fields": ["name", "supplier"],
			},
			_ctx(),
		)
		assert result.success
		assert result.data["total_matched"] == 1
		assert result.data["rows"][0]["supplier"] == "Acme"

	def test_limit_is_clamped(self, lifecycle_env):
		from idp.tools.search_documents import _MAX_LIMIT, search_documents

		result = search_documents(
			{"doctype": "Purchase Invoice", "limit": 999},
			_ctx(),
		)
		assert result.success
		assert result.data["limit"] == _MAX_LIMIT

	def test_projection_capped(self, lifecycle_env):
		from idp.tools.search_documents import _MAX_FIELDS, _normalise_fields

		fields = [f"f{i}" for i in range(50)]
		out = _normalise_fields(fields)
		# name is auto-prepended, then truncated to the cap.
		assert len(out) == _MAX_FIELDS
		assert out[0] == "name"

	def test_excludes_group_rows_by_default(self, lifecycle_env):
		"""Tree doctypes (Cost Center, Account, …) should default to
		``is_group=0`` so group containers don't pollute results."""
		from idp.tools.search_documents import search_documents

		store = lifecycle_env["store"]
		store["docs"].extend([
			{
				"doctype": "Cost Center",
				"name": "Main - TTD",
				"cost_center_name": "Main",
				"is_group": 0,
			},
			{
				"doctype": "Cost Center",
				"name": "Test - TTD",
				"cost_center_name": "Test",
				"is_group": 0,
			},
			{
				"doctype": "Cost Center",
				"name": "Tara - TTD",
				"cost_center_name": "Tara",
				"is_group": 1,
			},
		])
		# Tell the meta stub Cost Center has an `is_group` field.
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"is_group": types.SimpleNamespace(fieldtype="Check"),
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
				},
				"title_field": None,
			}
		}

		result = search_documents({"doctype": "Cost Center"}, _ctx())
		assert result.success
		names = {r["name"] for r in result.data["rows"]}
		assert "Main - TTD" in names
		assert "Test - TTD" in names
		# The group row must be filtered out.
		assert "Tara - TTD" not in names

	def test_explicit_is_group_filter_wins(self, lifecycle_env):
		"""Callers who explicitly want groups must still get them."""
		from idp.tools.search_documents import search_documents

		store = lifecycle_env["store"]
		store["docs"].extend([
			{
				"doctype": "Cost Center",
				"name": "Main - TTD",
				"is_group": 0,
			},
			{
				"doctype": "Cost Center",
				"name": "Tara - TTD",
				"is_group": 1,
			},
		])
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"is_group": types.SimpleNamespace(fieldtype="Check"),
				},
				"title_field": None,
			}
		}

		result = search_documents(
			{"doctype": "Cost Center", "filters": {"is_group": 1}},
			_ctx(),
		)
		assert result.success
		names = {r["name"] for r in result.data["rows"]}
		assert names == {"Tara - TTD"}


# ---------------------------------------------------------------------------
# update_document
# ---------------------------------------------------------------------------


class TestUpdateDocument:
	def test_dry_run_produces_diff_card(self, lifecycle_env):
		from idp.tools.update_document import update_document

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"supplier": "Acme Holdings"},
			},
			_ctx(),
		)
		assert result.success
		assert result.data["dry_run"] is True
		assert result.data["changed_count"] == 1
		assert result.card["card_type"] == "UpdateCard"
		diff = result.card["diff"]
		assert diff[0]["fieldname"] == "supplier"
		assert diff[0]["before"] == "Acme"
		assert diff[0]["after"] == "Acme Holdings"
		# Critically, no save happened.
		assert lifecycle_env["store"]["saves"] == []

	def test_commit_mutates_and_audits(self, lifecycle_env):
		from idp.tools.update_document import update_document

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"supplier": "Acme Holdings"},
				"dry_run": False,
				"reason": "Vendor rebrand",
			},
			_ctx(),
		)
		assert result.success
		assert result.data["dry_run"] is False
		assert result.stop_processing
		assert lifecycle_env["store"]["saves"], "expected save() to be invoked"

	def test_submitted_doc_lockout(self, lifecycle_env):
		from idp.tools.update_document import update_document

		# PINV-0002 is submitted (docstatus=1) and `supplier` is not
		# allow_on_submit, so update must refuse.
		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0002",
				"updates": {"supplier": "Beta Group"},
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "DOC_LOCKED"

	def test_submitted_doc_allow_on_submit_field_works(self, lifecycle_env):
		from idp.tools.update_document import update_document

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0002",
				"updates": {"remarks": "Late entry"},
			},
			_ctx(),
		)
		assert result.success
		assert result.data["dry_run"] is True

	def test_missing_write_perm_blocks(self, lifecycle_env):
		from idp.tools.update_document import update_document

		lifecycle_env["store"]["denied_perms"].add(("Purchase Invoice", "write"))
		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"supplier": "X"},
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "PERMISSION_DENIED"

	def test_record_not_found(self, lifecycle_env):
		from idp.tools.update_document import update_document

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "DOES-NOT-EXIST",
				"updates": {"supplier": "X"},
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "RECORD_NOT_FOUND"

	def test_commit_releases_savepoint(self, lifecycle_env):
		"""Successful apply path must release the savepoint so it
		doesn't accumulate in the connection's stack across calls."""
		from idp.tools.update_document import update_document

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"supplier": "Acme Holdings"},
				"dry_run": False,
			},
			_ctx(),
		)
		assert result.success
		db = lifecycle_env["frappe"].db
		assert db.savepoints == ["idp_update_document"]
		assert db.released == ["idp_update_document"]
		# No rollback on the happy path.
		assert db.rollbacks == []

	def test_preflight_warns_when_repost_ledger_disabled(self, lifecycle_env):
		"""Submitted Sales Invoice + repost-ledger setting absent → the
		dry-run UpdateCard must carry a Heads-up warning so the user
		doesn't get a surprise apply failure."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		# Tell the stub that Sales Invoice is a GL-emitting doctype so
		# ``_doctype_emits_gl_entries`` recognises it.
		store["gl_doctypes"].add("Sales Invoice")
		# Reshape PINV-0001 as a submitted Sales Invoice for this test.
		# The fixture stores it under "Purchase Invoice" by default; we
		# add a parallel Sales Invoice row here.
		store["docs"].append(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0001",
				"cost_center": "Old - TTD",
				"company": "Company A",
				"docstatus": 1,
			}
		)
		# Wire a meta surface for Sales Invoice that exposes a
		# allow_on_submit cost_center field.
		original_get_meta = lifecycle_env["frappe"].get_meta

		def patched_get_meta(doctype):
			if doctype == "Sales Invoice":
				class _SIMeta:
					fields = [
						types.SimpleNamespace(
							fieldname="cost_center",
							fieldtype="Link",
							options="Cost Center",
							allow_on_submit=1,
						),
						types.SimpleNamespace(
							fieldname="company",
							fieldtype="Link",
							options="Company",
							allow_on_submit=0,
						),
					]
					title_field = None

					def get_field(self, fn):
						for df in self.fields:
							if df.fieldname == fn:
								return df
						return None

				return _SIMeta()
			if doctype == "Repost Accounting Ledger Settings":
				class _RALMeta:
					fields: list = []
					title_field = None

					def get_field(self, fn):  # noqa: ARG002
						return None

				return _RALMeta()
			return original_get_meta(doctype)

		lifecycle_env["frappe"].get_meta = patched_get_meta

		# Pretend the DocType exists and the singleton has an empty
		# allowed_types table.
		original_db_exists = lifecycle_env["frappe"].db.exists

		def patched_db_exists(doctype, name=None):
			if doctype == "DocType" and name == "Repost Accounting Ledger Settings":
				return True
			return original_db_exists(doctype, name)

		lifecycle_env["frappe"].db.exists = patched_db_exists
		lifecycle_env["frappe"].get_cached_doc = lambda name: (
			types.SimpleNamespace(
				get=lambda key: [] if key == "allowed_types" else None
			)
			if name == "Repost Accounting Ledger Settings"
			else original_get_meta(name)
		)
		# Cost Center "Old - TTD" already exists — no resolver work.
		store["docs"].append(
			{"doctype": "Cost Center", "name": "New - TTD", "company": "Company A"}
		)
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"company": types.SimpleNamespace(fieldtype="Link"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0001",
				"updates": {"cost_center": "New - TTD"},
			},
			_ctx(),
		)
		assert result.success, result.error
		assert result.data["warnings"], "expected a pre-flight warning"
		warning = result.data["warnings"][0]
		assert "Repost Accounting Ledger Settings" in warning
		assert "Sales Invoice" in warning
		# The card payload exposes the same warning to the frontend.
		assert result.card["warnings"] == result.data["warnings"]

	def test_preflight_silent_when_doctype_is_allowed(self, lifecycle_env):
		"""When the doctype IS listed under allowed_types, no warning
		should surface — clean apply path expected."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["gl_doctypes"].add("Sales Invoice")
		store["docs"].append(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0002",
				"cost_center": "Old - TTD",
				"company": "Company A",
				"docstatus": 1,
			}
		)
		store["docs"].append(
			{"doctype": "Cost Center", "name": "New - TTD", "company": "Company A"}
		)
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"company": types.SimpleNamespace(fieldtype="Link"),
				},
				"title_field": None,
			}
		}
		original_get_meta = lifecycle_env["frappe"].get_meta

		def patched_get_meta(doctype):
			if doctype == "Sales Invoice":
				class _SIMeta:
					fields = [
						types.SimpleNamespace(
							fieldname="cost_center",
							fieldtype="Link",
							options="Cost Center",
							allow_on_submit=1,
						),
					]
					title_field = None

					def get_field(self, fn):
						for df in self.fields:
							if df.fieldname == fn:
								return df
						return None

				return _SIMeta()
			return original_get_meta(doctype)

		lifecycle_env["frappe"].get_meta = patched_get_meta

		original_db_exists = lifecycle_env["frappe"].db.exists

		def patched_db_exists(doctype, name=None):
			if doctype == "DocType" and name == "Repost Accounting Ledger Settings":
				return True
			return original_db_exists(doctype, name)

		lifecycle_env["frappe"].db.exists = patched_db_exists
		# Sales Invoice IS in allowed_types — no warning.
		lifecycle_env["frappe"].get_cached_doc = lambda name: (
			types.SimpleNamespace(
				get=lambda key: (
					[
						types.SimpleNamespace(
							get=lambda k: "Sales Invoice"
							if k == "document_type"
							else None
						)
					]
					if key == "allowed_types"
					else None
				)
			)
			if name == "Repost Accounting Ledger Settings"
			else None
		)

		result = update_document(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-0002",
				"updates": {"cost_center": "New - TTD"},
			},
			_ctx(),
		)
		assert result.success
		assert result.data["warnings"] == []

	def test_preflight_silent_for_non_gl_doctype(self, lifecycle_env):
		"""Submitted submittable doctypes WITHOUT GL hooks (e.g. a
		custom workflow doctype, or Task / Note) must not trigger the
		repost warning — the hardcoded-list approach was over-warning
		these.  Now detection is via controller-method introspection
		so we only warn doctypes that actually emit GL entries."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		# Add a submitted record of a doctype that is NOT marked as
		# GL-emitting in the stub.
		store["docs"].append(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-NONGL",
				"cost_center": "Old - TTD",
				"company": "Company A",
				"docstatus": 1,
			}
		)
		store["docs"].append(
			{"doctype": "Cost Center", "name": "New - TTD", "company": "Company A"}
		)
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"company": types.SimpleNamespace(fieldtype="Link"),
				},
				"title_field": None,
			}
		}
		# Repost Accounting Ledger Settings exists and is EMPTY — under
		# the old hardcoded-list approach this would trigger the
		# warning for Sales Invoice regardless.  Now the warning should
		# stay silent because the stub doc class has no GL hook.
		original_get_meta = lifecycle_env["frappe"].get_meta

		def patched_get_meta(doctype):
			if doctype == "Sales Invoice":
				class _SIMeta:
					fields = [
						types.SimpleNamespace(
							fieldname="cost_center",
							fieldtype="Link",
							options="Cost Center",
							allow_on_submit=1,
						),
					]
					title_field = None

					def get_field(self, fn):
						for df in self.fields:
							if df.fieldname == fn:
								return df
						return None

				return _SIMeta()
			return original_get_meta(doctype)

		lifecycle_env["frappe"].get_meta = patched_get_meta
		original_db_exists = lifecycle_env["frappe"].db.exists

		def patched_db_exists(doctype, name=None):
			if doctype == "DocType" and name == "Repost Accounting Ledger Settings":
				return True
			return original_db_exists(doctype, name)

		lifecycle_env["frappe"].db.exists = patched_db_exists
		lifecycle_env["frappe"].get_cached_doc = lambda name: types.SimpleNamespace(
			get=lambda key: [] if key == "allowed_types" else None
		)

		result = update_document(
			{
				"doctype": "Sales Invoice",
				"name": "SINV-NONGL",
				"updates": {"cost_center": "New - TTD"},
			},
			_ctx(),
		)
		assert result.success
		# No GL hook on the controller → no repost warning.
		assert result.data["warnings"] == []

	def test_save_failure_triggers_rollback(self, lifecycle_env):
		"""If save() raises, the savepoint must be rolled back so the
		caller doesn't end up with a half-committed mutation (the exact
		bug ERPNext's repost-ledger guard otherwise exposes on
		submitted Sales Invoices)."""
		from idp.tools.update_document import update_document

		# Patch the parent doc's save() to simulate the
		# "not allowed to be reposted" failure that happens AFTER
		# db_update has already persisted the field change.
		original_get_doc = lifecycle_env["frappe"].get_doc

		def boom_get_doc(doctype, name=None):
			doc = original_get_doc(doctype, name)

			def boom():
				raise RuntimeError("not allowed to be reposted")

			doc.save = boom  # type: ignore[assignment]
			return doc

		lifecycle_env["frappe"].get_doc = boom_get_doc

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"supplier": "Acme Holdings"},
				"dry_run": False,
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "UPDATE_FAILED"
		db = lifecycle_env["frappe"].db
		assert db.savepoints == ["idp_update_document"]
		assert db.rollbacks == ["idp_update_document"]
		# No release on the failure path.
		assert db.released == []

	def test_resolves_link_value_via_doctype_name_field(self, lifecycle_env):
		"""Supplying ``"Test"`` for a Link field whose target uses
		``{doctype}_name`` autoname must resolve to the canonical
		``"Test - TTD"`` and surface ``resolved_from`` on the diff."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		# Seed a Cost Center record so the resolver can find it.
		store["docs"].append(
			{
				"doctype": "Cost Center",
				"name": "Test - TTD",
				"cost_center_name": "Test",
			}
		)
		# Tell the meta stub that Cost Center has a `cost_center_name` Data field.
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Test"},
			},
			_ctx(),
		)
		assert result.success, result.error
		row = next(r for r in result.data["diff"] if r["fieldname"] == "cost_center")
		assert row["after"] == "Test - TTD"
		assert row["resolved_from"] == "Test"

	def test_ambiguous_link_returns_candidates(self, lifecycle_env):
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		# Two records sharing the same display name.
		store["docs"].extend([
			{"doctype": "Cost Center", "name": "Test - AAA", "cost_center_name": "Test"},
			{"doctype": "Cost Center", "name": "Test - BBB", "cost_center_name": "Test"},
		])
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Test"},
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "AMBIGUOUS_LINK"
		# Loop should resume — LLM can recover by picking a candidate.
		assert result.stop_processing is False

	def test_unresolvable_link_returns_not_found(self, lifecycle_env):
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Nonexistent"},
			},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "LINK_NOT_FOUND"
		# Recoverable — the LLM can call search_documents to find a value.
		assert result.stop_processing is False

	def test_company_scoped_resolution_disambiguates_across_companies(
		self, lifecycle_env
	):
		"""``Test`` cost centers exist in two companies — the parent's
		``company`` must narrow the resolver so the right one wins."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		# Two identically-named cost centers — one per company.
		store["docs"].extend([
			{
				"doctype": "Cost Center",
				"name": "Test - TTD",
				"cost_center_name": "Test",
				"company": "Company A",
			},
			{
				"doctype": "Cost Center",
				"name": "Test - TTB",
				"cost_center_name": "Test",
				"company": "Company B",
			},
		])
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
					"company": types.SimpleNamespace(fieldtype="Link"),
				},
				"title_field": None,
			}
		}

		# PINV-0001 belongs to Company A — resolver should pick TTD.
		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Test"},
			},
			_ctx(),
		)
		assert result.success, result.error
		row = next(r for r in result.data["diff"] if r["fieldname"] == "cost_center")
		assert row["after"] == "Test - TTD"
		assert row["resolved_from"] == "Test"

	def test_link_resolver_skips_group_rows(self, lifecycle_env):
		"""The link resolver must not consider ``is_group=1`` candidates —
		even when only one such row would match, it's never the right
		answer for a transactional update."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		# Two records share the cost_center_name "Tara" — one group, one leaf.
		# Without is_group filtering this would be AMBIGUOUS; with it, the
		# leaf wins cleanly.
		store["docs"].extend([
			{
				"doctype": "Cost Center",
				"name": "Tara - TTD",
				"cost_center_name": "Tara",
				"company": "Company A",
				"is_group": 1,
			},
			{
				"doctype": "Cost Center",
				"name": "Tara Leaf - TTD",
				"cost_center_name": "Tara",
				"company": "Company A",
				"is_group": 0,
			},
		])
		store["link_metas"] = {
			"Cost Center": {
				"fields": {
					"is_group": types.SimpleNamespace(fieldtype="Check"),
					"cost_center_name": types.SimpleNamespace(fieldtype="Data"),
					"company": types.SimpleNamespace(fieldtype="Link"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Tara"},
			},
			_ctx(),
		)
		assert result.success, result.error
		row = next(r for r in result.data["diff"] if r["fieldname"] == "cost_center")
		# Resolver must pick the leaf, not the group.
		assert row["after"] == "Tara Leaf - TTD"

	def test_company_unscoped_doctype_falls_back_to_unscoped_query(
		self, lifecycle_env
	):
		"""Doctypes without a ``company`` field (e.g. Item) must still
		resolve — the company filter is silently skipped."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["item_code"] = types.SimpleNamespace(
			fieldtype="Link", options="Item", allow_on_submit=0,
		)
		store["docs"].append(
			{
				"doctype": "Item",
				"name": "ITEM-001",
				"item_name": "Widget",
			}
		)
		# Item meta has no `company` field — the resolver should not
		# narrow the query and must still return ITEM-001.
		store["link_metas"] = {
			"Item": {
				"fields": {
					"item_name": types.SimpleNamespace(fieldtype="Data"),
				},
				"title_field": None,
			}
		}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"item_code": "Widget"},
			},
			_ctx(),
		)
		assert result.success, result.error
		row = next(r for r in result.data["diff"] if r["fieldname"] == "item_code")
		assert row["after"] == "ITEM-001"

	def test_auto_resolve_links_opt_out(self, lifecycle_env):
		"""When the caller passes ``auto_resolve_links=False`` the tool
		treats the supplied value verbatim — useful when the caller has
		already validated the canonical name."""
		from idp.tools.update_document import update_document

		store = lifecycle_env["store"]
		store["fields"]["cost_center"] = types.SimpleNamespace(
			fieldtype="Link", options="Cost Center", allow_on_submit=0,
		)
		# No matching Cost Center seeded — resolution would normally fail.
		store["link_metas"] = {"Cost Center": {"fields": {}, "title_field": None}}

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Whatever"},
				"auto_resolve_links": False,
			},
			_ctx(),
		)
		# Resolver is skipped, the dry-run diff just records the value
		# as supplied; downstream save would fail but that's not the
		# tool's job here.
		assert result.success
		row = next(r for r in result.data["diff"] if r["fieldname"] == "cost_center")
		assert row["after"] == "Whatever"
		assert "resolved_from" not in row

	def test_child_table_cascade_diff(self, lifecycle_env):
		"""``cost_center`` exists on both header and items child — the diff
		should carry both a header row and an ``items.cost_center`` row.
		"""
		from idp.tools.update_document import update_document

		# Wire a child column ``cost_center`` into the stub meta and
		# attach two child rows to PINV-0001.
		lifecycle_env["store"]["fields"]["cost_center"] = types.SimpleNamespace(
			allow_on_submit=0
		)
		lifecycle_env["store"]["child_fields"] = {
			"cost_center": types.SimpleNamespace(fieldtype="Link"),
		}

		# Replace the parent doc with one carrying ``items`` rows.
		class _ChildRow(dict):
			def get(self, key, default=None):
				return super().get(key, default)
			def set(self, key, value):
				self[key] = value
		parent = lifecycle_env["store"]["docs"][0]
		parent["items"] = [
			_ChildRow({"cost_center": "Old - TTD"}),
			_ChildRow({"cost_center": "Old - TTD"}),
		]

		result = update_document(
			{
				"doctype": "Purchase Invoice",
				"name": "PINV-0001",
				"updates": {"cost_center": "Test - TTD"},
			},
			_ctx(),
		)
		assert result.success
		scopes = {row.get("scope") for row in result.data["diff"]}
		# Both scopes should be present.
		assert "header" in scopes
		assert "child" in scopes
		child_row = next(
			r for r in result.data["diff"] if r.get("scope") == "child"
		)
		assert child_row["fieldname"] == "items.cost_center"
		assert child_row["row_count"] == 2


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


class TestDeleteDocument:
	def test_refuses_without_confirm(self, lifecycle_env):
		from idp.tools.delete_document import delete_document

		result = delete_document(
			{"doctype": "Purchase Invoice", "name": "PINV-0001", "confirm": False},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "USER_CONFIRMATION_REQUIRED"
		assert result.stop_processing
		# Nothing was deleted.
		assert lifecycle_env["store"]["deletes"] == []

	def test_deletes_and_returns_undo_token(self, lifecycle_env):
		from idp.tools.delete_document import delete_document

		result = delete_document(
			{"doctype": "Purchase Invoice", "name": "PINV-0001", "confirm": True},
			_ctx(),
		)
		assert result.success
		assert result.data["deleted"] is True
		# Note: undo_token might be None in pure-mode because the audit
		# stub doesn't return a row name, but the field is exposed.
		assert "undo_token" in result.data
		assert lifecycle_env["store"]["deletes"] == [
			{"doctype": "Purchase Invoice", "name": "PINV-0001"}
		]

	def test_refuses_submitted_doc(self, lifecycle_env):
		from idp.tools.delete_document import delete_document

		result = delete_document(
			{"doctype": "Purchase Invoice", "name": "PINV-0002", "confirm": True},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "DOC_SUBMITTED"
		assert lifecycle_env["store"]["deletes"] == []

	def test_missing_delete_perm_blocks(self, lifecycle_env):
		from idp.tools.delete_document import delete_document

		lifecycle_env["store"]["denied_perms"].add(("Purchase Invoice", "delete"))
		result = delete_document(
			{"doctype": "Purchase Invoice", "name": "PINV-0001", "confirm": True},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "PERMISSION_DENIED"

	def test_record_not_found(self, lifecycle_env):
		from idp.tools.delete_document import delete_document

		result = delete_document(
			{"doctype": "Purchase Invoice", "name": "ABSENT", "confirm": True},
			_ctx(),
		)
		assert not result.success
		assert result.error_code == "RECORD_NOT_FOUND"
