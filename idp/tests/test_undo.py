# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 32 — Reversibility / Undo: unit tests.

Pure-mode tests (no Frappe site required) covering:

* ``get_undo_window_minutes`` parses settings sensibly and falls back
  to 5 on bad / missing input.
* ``_reverse_doc`` deletes drafts, cancels submitted submittable
  docs, and refuses non-submittable submitted ones.
* ``undo_confirmation`` rejects:
    - disabled feature (window <= 0)
    - guests
    - non-owners (unless System Manager)
    - expired deadlines
    - missing created_doctype/docname
    - already-undone cards (re-click is a friendly no-op)
* Phase 31 error map carries the new undo entries.

Bench integration (Frappe site DB) is exercised by the existing
``confirm_card`` end-to-end suite — pure-mode here verifies the
deterministic helpers and the authorisation gate.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Frappe stub tailored for the undo endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def undo_frappe(monkeypatch):
	"""Install a minimal ``frappe`` + ``frappe.utils`` stub for undo tests."""
	mod = types.ModuleType("frappe")

	class _Session:
		user = "alice@example.com"

	class _DB:
		def __init__(self):
			self.single_values = {"undo_window_minutes": 5}
			self.exists_map = {}
			self.get_value_map = {}
			self.committed = 0
			self.sql_log = []

		def commit(self):
			self.committed += 1

		def get_single_value(self, _doctype, fieldname):
			return self.single_values.get(fieldname)

		def exists(self, doctype, name):
			return self.exists_map.get((doctype, name), False)

		def get_value(self, doctype, name, fieldname):
			return self.get_value_map.get((doctype, name, fieldname))

		def sql(self, q, *a, **kw):  # noqa: ARG002
			self.sql_log.append(q)
			return []

	docs_by_key: dict[tuple[str, str], "_Doc"] = {}

	class _Doc(dict):
		def __init__(self, data):
			super().__init__(data)
			self.name = data.get("name") or "<unnamed>"
			# Action counters so tests can assert on .delete()/.cancel()/.save().
			self.deleted = 0
			self.cancelled = 0
			self.saved = 0
			self.inserted = 0
			self.docstatus = data.get("docstatus", 0)

		def get(self, key, default=None):
			return super().get(key, default)

		def __getattr__(self, key):
			# Treat dict keys as attributes so frappe-style ``doc.field``
			# access works in addition to ``doc["field"]``.  Returns
			# ``None`` for unknown keys to mirror Frappe's lenient
			# accessor.
			if key.startswith("_"):
				raise AttributeError(key)
			return self.get(key, None)

		def __setattr__(self, key, value):
			# Mirror the assignment into the dict so reads via ``.get()``
			# and ``["field"]`` see the change.
			if key in {
				"name",
				"deleted",
				"cancelled",
				"saved",
				"inserted",
				"docstatus",
			}:
				object.__setattr__(self, key, value)
			else:
				self[key] = value

		def delete(self):
			self.deleted += 1

		def cancel(self):
			self.cancelled += 1
			self.docstatus = 2

		def save(self, ignore_permissions=False):  # noqa: ARG002
			self.saved += 1
			return self

		def insert(self, ignore_permissions=False):  # noqa: ARG002
			self.inserted += 1
			return self

		def as_dict(self):
			return dict(self)

	def get_doc(arg, name=None):
		if isinstance(arg, str):
			key = (arg, name)
			if key in docs_by_key:
				return docs_by_key[key]
			# Allow ad-hoc fetch with empty defaults so tests can attach
			# the doc afterwards.
			doc = _Doc({"doctype": arg, "name": name})
			docs_by_key[key] = doc
			return doc
		# Dict path — used by audit.log_event and ack message inserts.
		doc = _Doc(arg)
		return doc

	def get_single(_name):
		return SimpleNamespace(**mod.db.single_values)

	def get_cached_doc(_name):
		return SimpleNamespace(**mod.db.single_values)

	def get_roles(_user):
		return ["IDP User"]

	class _Throw(Exception):
		pass

	class _Permission(_Throw):
		pass

	class _Validation(_Throw):
		pass

	class _Auth(_Throw):
		pass

	class _NotFound(_Throw):
		pass

	class _LinkExists(_Throw):
		pass

	def throw(msg, exc_cls=None, *a, **kw):  # noqa: ARG001
		if exc_cls is mod.PermissionError:
			raise _Permission(msg)
		if exc_cls is mod.ValidationError:
			raise _Validation(msg)
		if exc_cls is mod.AuthenticationError:
			raise _Auth(msg)
		if exc_cls is mod.DoesNotExistError:
			raise _NotFound(msg)
		raise _Throw(msg)

	def whitelist(*_a, **_kw):
		def wrap(fn):
			return fn

		return wrap

	def new_doc(doctype):
		return _Doc({"doctype": doctype})

	def publish_realtime(*_a, **_kw):
		pass

	def log_error(*_a, **_kw):
		pass

	import logging

	def logger(name, *_a, **_kw):  # noqa: ARG001
		return logging.getLogger(name)

	mod.session = _Session()
	mod.db = _DB()
	mod.get_doc = get_doc
	mod.get_single = get_single
	mod.get_cached_doc = get_cached_doc
	mod.get_roles = get_roles
	mod.new_doc = new_doc
	mod.publish_realtime = publish_realtime
	mod.log_error = log_error
	mod.whitelist = whitelist
	mod.throw = throw
	mod.logger = logger
	mod.PermissionError = _Permission
	mod.ValidationError = _Validation
	mod.AuthenticationError = _Auth
	mod.DoesNotExistError = _NotFound
	mod.LinkExistsError = _LinkExists
	mod._docs_by_key = docs_by_key  # exposed for assertions

	# ---- frappe.utils -------------------------------------------------
	utils_mod = types.ModuleType("frappe.utils")

	def now_datetime():
		return now_datetime._frozen

	now_datetime._frozen = datetime(2026, 5, 1, 12, 0, 0)

	def add_to_date(dt, minutes=0, hours=0, days=0, **_kw):
		if isinstance(dt, str):
			dt = datetime.fromisoformat(dt)
		return dt + timedelta(minutes=minutes, hours=hours, days=days)

	def get_datetime(value):
		if isinstance(value, datetime):
			return value
		return datetime.fromisoformat(str(value))

	def get_datetime_str(value):
		return get_datetime(value).strftime("%Y-%m-%d %H:%M:%S")

	def get_url_to_form(doctype, name):
		return f"/app/{doctype.lower().replace(' ', '-')}/{name}"

	utils_mod.now_datetime = now_datetime
	utils_mod.add_to_date = add_to_date
	utils_mod.get_datetime = get_datetime
	utils_mod.get_datetime_str = get_datetime_str
	utils_mod.get_url_to_form = get_url_to_form
	mod.utils = utils_mod

	# ---- frappe._ translation helper ---------------------------------
	mod._ = lambda s: s

	# ---- frappe.local --------------------------------------------------
	mod.local = SimpleNamespace(lang="en")

	monkeypatch.setitem(sys.modules, "frappe", mod)
	monkeypatch.setitem(sys.modules, "frappe.utils", utils_mod)

	# audit module imports frappe at module scope — force reload so it
	# sees our stub instead of an older import.
	import importlib

	if "idp.core.audit" in sys.modules:
		importlib.reload(sys.modules["idp.core.audit"])
	if "idp.api.undo" in sys.modules:
		importlib.reload(sys.modules["idp.api.undo"])
	return mod


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


class TestGetUndoWindowMinutes:
	def test_default_when_missing(self, undo_frappe):
		undo_frappe.db.single_values.pop("undo_window_minutes", None)
		from idp.api.undo import get_undo_window_minutes

		assert get_undo_window_minutes() == 5

	def test_negative_clamped_to_zero(self, undo_frappe):
		undo_frappe.db.single_values["undo_window_minutes"] = -10
		from idp.api.undo import get_undo_window_minutes

		assert get_undo_window_minutes() == 0

	def test_zero_disables_feature(self, undo_frappe):
		undo_frappe.db.single_values["undo_window_minutes"] = 0
		from idp.api.undo import get_undo_window_minutes

		assert get_undo_window_minutes() == 0

	def test_string_parsed(self, undo_frappe):
		undo_frappe.db.single_values["undo_window_minutes"] = "7"
		from idp.api.undo import get_undo_window_minutes

		assert get_undo_window_minutes() == 7

	def test_bad_value_falls_back(self, undo_frappe):
		undo_frappe.db.single_values["undo_window_minutes"] = "nope"
		from idp.api.undo import get_undo_window_minutes

		assert get_undo_window_minutes() == 5


# ---------------------------------------------------------------------------
# _reverse_doc
# ---------------------------------------------------------------------------


def _install_target(undo_frappe, *, doctype, name, docstatus, is_submittable=True):
	# Pre-register the target doc and the DocType metadata used by
	# _reverse_doc to gate cancel vs error.
	undo_frappe.db.exists_map[(doctype, name)] = True
	undo_frappe.db.get_value_map[("DocType", doctype, "is_submittable")] = (
		1 if is_submittable else 0
	)
	doc = undo_frappe.get_doc(doctype, name)
	doc["docstatus"] = docstatus
	doc.docstatus = docstatus
	return doc


class TestReverseDoc:
	def test_deletes_draft(self, undo_frappe):
		from idp.api.undo import _reverse_doc

		doc = _install_target(undo_frappe, doctype="Sales Invoice", name="SI-1", docstatus=0)
		result = _reverse_doc("Sales Invoice", "SI-1")
		assert result["action"] == "deleted"
		assert doc.deleted == 1

	def test_cancels_submitted_submittable(self, undo_frappe):
		from idp.api.undo import _reverse_doc

		doc = _install_target(undo_frappe, doctype="Sales Invoice", name="SI-2", docstatus=1)
		result = _reverse_doc("Sales Invoice", "SI-2")
		assert result["action"] == "cancelled"
		assert doc.cancelled == 1

	def test_refuses_non_submittable_submitted(self, undo_frappe):
		from idp.api.undo import _reverse_doc

		_install_target(
			undo_frappe,
			doctype="Customer",
			name="CUST-1",
			docstatus=1,
			is_submittable=False,
		)
		with pytest.raises(undo_frappe.ValidationError):
			_reverse_doc("Customer", "CUST-1")

	def test_already_cancelled_is_noop(self, undo_frappe):
		from idp.api.undo import _reverse_doc

		_install_target(undo_frappe, doctype="Sales Invoice", name="SI-3", docstatus=2)
		result = _reverse_doc("Sales Invoice", "SI-3")
		assert result["action"] == "noop"
		assert result["reason"] == "already_cancelled"

	def test_missing_document_is_noop(self, undo_frappe):
		from idp.api.undo import _reverse_doc

		result = _reverse_doc("Sales Invoice", "MISSING")
		assert result["action"] == "noop"
		assert result["reason"] == "document_not_found"


# ---------------------------------------------------------------------------
# undo_confirmation — end-to-end (in-memory)
# ---------------------------------------------------------------------------


def _make_message(undo_frappe, *, name="IDP-MSG-1", deadline_minutes=4):
	"""Persist an IDP Message in the stub so undo_confirmation finds it."""
	deadline = undo_frappe.utils.now_datetime() + timedelta(minutes=deadline_minutes)
	msg = undo_frappe.get_doc("IDP Message", name)
	msg.update(
		{
			"doctype": "IDP Message",
			"name": name,
			"conversation": "IDP-CONV-1",
			"created_doctype": "Sales Invoice",
			"created_docname": "SI-100",
			"undo_deadline": deadline,
			"rendered_card_payload": json.dumps(
				{
					"card_type": "ConfirmationCard",
					"undo": {
						"deadline": undo_frappe.utils.get_datetime_str(deadline),
						"window_minutes": 5,
						"created_doctype": "Sales Invoice",
						"created_docname": "SI-100",
					},
				}
			),
		}
	)
	# Also seed the conversation owner so the auth check passes.
	conv = undo_frappe.get_doc("IDP Conversation", "IDP-CONV-1")
	conv["owner"] = undo_frappe.session.user
	conv.owner = undo_frappe.session.user
	return msg


class TestUndoConfirmation:
	def test_disabled_when_window_zero(self, undo_frappe):
		undo_frappe.db.single_values["undo_window_minutes"] = 0
		_make_message(undo_frappe)
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.ValidationError):
			undo_confirmation("IDP-MSG-1")

	def test_rejects_guest(self, undo_frappe):
		undo_frappe.session.user = "Guest"
		_make_message(undo_frappe)
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.AuthenticationError):
			undo_confirmation("IDP-MSG-1")

	def test_rejects_non_owner(self, undo_frappe):
		# Owner is alice; bob tries to undo.
		_make_message(undo_frappe)
		undo_frappe.session.user = "bob@example.com"
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.PermissionError):
			undo_confirmation("IDP-MSG-1")

	def test_system_manager_can_undo_other_user_card(self, undo_frappe):
		_make_message(undo_frappe)
		_install_target(undo_frappe, doctype="Sales Invoice", name="SI-100", docstatus=0)
		# Different user, but they hold System Manager.
		undo_frappe.session.user = "admin@example.com"
		undo_frappe.get_roles = lambda _u: ["System Manager"]  # type: ignore[attr-defined]
		import idp.api.undo as undo_mod
		import importlib

		importlib.reload(undo_mod)
		# After reload re-stub get_roles (reload re-imports frappe).
		undo_frappe.get_roles = lambda _u: ["System Manager"]
		# Patch the module-level reference too because _is_system_manager
		# imports frappe lazily at call time, so this is sufficient.

		result = undo_mod.undo_confirmation("IDP-MSG-1")
		assert result["action"] == "deleted"

	def test_rejects_expired_window(self, undo_frappe):
		# Deadline 1 minute in the past.
		_make_message(undo_frappe, deadline_minutes=-1)
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.ValidationError):
			undo_confirmation("IDP-MSG-1")

	def test_rejects_already_undone(self, undo_frappe):
		msg = _make_message(undo_frappe)
		card = json.loads(msg["rendered_card_payload"])
		card["undone"] = True
		msg["rendered_card_payload"] = json.dumps(card)
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.ValidationError):
			undo_confirmation("IDP-MSG-1")

	def test_rejects_when_no_created_doc(self, undo_frappe):
		msg = _make_message(undo_frappe)
		msg["created_doctype"] = None
		msg["created_docname"] = None
		from idp.api.undo import undo_confirmation

		with pytest.raises(undo_frappe.ValidationError):
			undo_confirmation("IDP-MSG-1")

	def test_happy_path_deletes_draft_and_stamps_card(self, undo_frappe):
		msg = _make_message(undo_frappe)
		target = _install_target(
			undo_frappe, doctype="Sales Invoice", name="SI-100", docstatus=0
		)
		from idp.api.undo import undo_confirmation

		result = undo_confirmation("IDP-MSG-1")
		assert result["action"] == "deleted"
		assert target.deleted == 1
		card = json.loads(msg["rendered_card_payload"])
		assert card["undone"] is True
		assert card["undo_result"]["action"] == "deleted"
		assert card["actions"] == []

	def test_happy_path_cancels_submitted(self, undo_frappe):
		msg = _make_message(undo_frappe)
		target = _install_target(
			undo_frappe, doctype="Sales Invoice", name="SI-100", docstatus=1
		)
		from idp.api.undo import undo_confirmation

		result = undo_confirmation("IDP-MSG-1")
		assert result["action"] == "cancelled"
		assert target.cancelled == 1
		card = json.loads(msg["rendered_card_payload"])
		assert card["undone"] is True
		assert card["undo_result"]["action"] == "cancelled"


# ---------------------------------------------------------------------------
# Unified error map entries
# ---------------------------------------------------------------------------


class TestErrorMap:
	def test_undo_window_expired_envelope(self):
		# Pure import — no Frappe needed.
		from idp.core.errors import ERROR_MAP

		assert "UndoWindowExpiredError" in ERROR_MAP
		entry = ERROR_MAP["UndoWindowExpiredError"]
		assert entry["recovery_action"] is None
		assert "expired" in entry["user_message"].lower()

	def test_undo_not_eligible_envelope(self):
		from idp.core.errors import ERROR_MAP

		assert "UndoNotEligibleError" in ERROR_MAP

	def test_undo_link_exists_envelope(self):
		from idp.core.errors import ERROR_MAP

		assert "UndoLinkExistsError" in ERROR_MAP
