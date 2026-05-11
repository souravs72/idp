# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Per-conversation file alias registry (Phase 18).

LLMs are unreliable when asked to quote long URLs like
``/private/files/A4-S2-GST-Invoice-Format.pdf`` — they shorten,
paraphrase, or invent similar paths.  This registry exposes every
attachment to the LLM as a short monotonic alias (``file_1``,
``file_2``, …) and resolves the alias back to the real ``file_url``
on every tool call.

Why monotonic ints rather than ``tabFile.name``?
``tabFile.name`` is a 10-character hex hash that sits squarely inside
the LLM's hallucination range — a one-character drift produces a
plausible-but-wrong key.  ``file_3`` is short enough that any LLM
mutation is immediately obvious and fails registry lookup.

The registry is the single source of truth for resolution; persistence
is via the ``IDP Conversation Attachment`` child table on
:class:`IDPConversation`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from idp.core.exceptions import FileAliasNotFoundError
from idp.core.logger import get_logger

logger = get_logger("idp.llm.file_alias")

ALIAS_PREFIX = "file_"


@dataclass
class AttachmentRecord:
	"""Per-attachment metadata stored in the registry."""

	alias: str
	file_url: str
	file_name: str
	mime_type: str = ""
	file_size: int | None = None
	tabfile_name: str | None = None  # internal — never exposed to LLM
	inline_text_preview: str = ""

	def to_public_dict(self) -> dict:
		"""Return a dict safe to ship in tool results.

		Excludes ``tabfile_name`` since it is an internal dedup key and
		must never reach the LLM (cf. Phase 18 §18.2).
		"""

		return {
			"alias": self.alias,
			"file_id": self.alias,
			"file_url": self.file_url,
			"file_name": self.file_name,
			"mime_type": self.mime_type,
			"file_size": self.file_size,
			"inline_text_preview": self.inline_text_preview,
		}


@dataclass
class FileAliasRegistry:
	"""Per-conversation bidirectional alias ↔ URL registry.

	The instance is normally cached on
	``frappe.flags.file_alias_registry[conversation_id]`` for the
	lifetime of a request.  Rebuild from the persisted child table via
	:meth:`load`.
	"""

	conversation_id: str
	_by_url: dict[str, str] = field(default_factory=dict)
	_by_alias: dict[str, AttachmentRecord] = field(default_factory=dict)
	_by_tabfile_name: dict[str, str] = field(default_factory=dict)

	# ---- registration -------------------------------------------------------

	def register(
		self,
		file_url: str,
		file_name: str,
		mime_type: str = "",
		*,
		tabfile_name: str | None = None,
		file_size: int | None = None,
		inline_text_preview: str = "",
	) -> str:
		"""Assign or reuse the alias for *file_url*.

		Dedup precedence:

		1. ``file_url`` already registered → return existing alias.
		2. ``tabfile_name`` (server-side dedup key) already registered
		   → return existing alias.  We update ``_by_url`` so future
		   lookups by URL also hit.
		3. Else assign the next monotonic alias
		   (``file_{len(_by_alias) + 1}``).
		"""

		if not file_url:
			raise ValueError("file_url is required")

		if file_url in self._by_url:
			alias = self._by_url[file_url]
			# Refresh metadata that may have grown (preview / size) without
			# changing the alias itself.
			self._update_metadata(
				alias,
				mime_type=mime_type,
				file_size=file_size,
				inline_text_preview=inline_text_preview,
			)
			return alias

		if tabfile_name and tabfile_name in self._by_tabfile_name:
			alias = self._by_tabfile_name[tabfile_name]
			self._by_url[file_url] = alias
			self._update_metadata(
				alias,
				mime_type=mime_type,
				file_size=file_size,
				inline_text_preview=inline_text_preview,
			)
			# Keep the canonical URL on the record consistent with what
			# the caller used so resolution returns the active path.
			self._by_alias[alias].file_url = file_url
			return alias

		alias = f"{ALIAS_PREFIX}{len(self._by_alias) + 1}"
		record = AttachmentRecord(
			alias=alias,
			file_url=file_url,
			file_name=file_name,
			mime_type=mime_type,
			file_size=file_size,
			tabfile_name=tabfile_name,
			inline_text_preview=inline_text_preview or "",
		)
		self._by_alias[alias] = record
		self._by_url[file_url] = alias
		if tabfile_name:
			self._by_tabfile_name[tabfile_name] = alias
		return alias

	# ---- resolution ---------------------------------------------------------

	def resolve(self, alias: str) -> AttachmentRecord | None:
		"""Return the record for *alias*, or ``None`` if unknown.

		Phase 27 §27.3 — also enforces file-level and parent-DocType
		permission checks via :func:`idp.core.security.check_file_access`
		so a user who can read a File row but not its attached parent
		(e.g. the underlying Sales Invoice) cannot exfiltrate parent
		data through OCR.  Permission failures raise
		:class:`IDPPermissionError`; callers that want to silently miss
		on permission denial should catch it explicitly.
		"""

		record = self._by_alias.get(alias)
		if record is not None:
			_enforce_file_access(record)
		return record

	def resolve_or_stop(self, alias: str) -> AttachmentRecord:
		"""Like :meth:`resolve` but raises :class:`FileAliasNotFoundError`.

		Tool wrappers should call this at the very start of every
		tool that takes a file alias so a stop-on-error response is
		emitted whenever the LLM hallucinates an alias.

		Phase 27 §27.3 — also runs :func:`check_file_access` to close
		the parent-DocType exfiltration gap (see :meth:`resolve`).
		"""

		record = self._by_alias.get(alias)
		if record is None:
			raise FileAliasNotFoundError(alias, conversation_id=self.conversation_id)
		_enforce_file_access(record)
		return record

	def url_for(self, alias: str) -> str | None:
		"""Convenience: return the URL for an alias, or ``None``."""

		record = self._by_alias.get(alias)
		return record.file_url if record else None

	# ---- introspection ------------------------------------------------------

	def items(self) -> list[AttachmentRecord]:
		"""Return all records ordered by their numeric alias suffix."""

		return [self._by_alias[a] for a in sorted(self._by_alias, key=_alias_sort_key)]

	def __len__(self) -> int:
		return len(self._by_alias)

	def __contains__(self, alias: str) -> bool:
		return alias in self._by_alias

	# ---- persistence --------------------------------------------------------

	@classmethod
	def load(cls, conversation_id: str) -> "FileAliasRegistry":
		"""Rebuild a registry from a conversation's persisted attachments."""

		registry = cls(conversation_id=conversation_id)
		try:
			import frappe
		except ImportError:
			return registry

		try:
			doc = frappe.get_doc("IDP Conversation", conversation_id)
		except Exception as exc:
			logger.debug(f"FileAliasRegistry.load: cannot read conversation {conversation_id}: {exc}")
			return registry

		# Sort by the numeric suffix on file_id so we honour the original
		# monotonic order rather than insertion order in the parent doc.
		rows = sorted(
			(r for r in (doc.attachments or []) if getattr(r, "file_url", None)),
			key=lambda r: _alias_sort_key(getattr(r, "file_id", None) or ""),
		)
		for row in rows:
			alias = (getattr(row, "file_id", None) or "").strip()
			if not alias:
				# Pre-Phase-18 rows may have no alias; assign the next one.
				alias = f"{ALIAS_PREFIX}{len(registry._by_alias) + 1}"
			# Insert directly so we preserve the persisted alias rather
			# than re-numbering via register().
			record = AttachmentRecord(
				alias=alias,
				file_url=row.file_url,
				file_name=getattr(row, "file_name", "") or "",
				mime_type=getattr(row, "mime_type", "") or "",
				file_size=getattr(row, "file_size", None),
				tabfile_name=getattr(row, "tabfile_name", None),
				inline_text_preview=getattr(row, "inline_text_preview", "") or "",
			)
			registry._by_alias[alias] = record
			registry._by_url[record.file_url] = alias
			if record.tabfile_name:
				registry._by_tabfile_name[record.tabfile_name] = alias
		return registry

	def persist(self) -> None:
		"""Persist any new attachments to the conversation's child table.

		Existing rows are not modified; this is a one-way "extend" so
		stable aliases survive across requests.
		"""

		try:
			import frappe
		except ImportError:
			return

		try:
			doc = frappe.get_doc("IDP Conversation", self.conversation_id)
		except Exception as exc:
			logger.debug(f"FileAliasRegistry.persist: cannot load conversation: {exc}")
			return

		existing = {row.file_id for row in (doc.attachments or []) if row.file_id}
		dirty = False
		for record in self.items():
			if record.alias in existing:
				continue
			doc.add_attachment(
				file_url=record.file_url,
				file_name=record.file_name,
				mime_type=record.mime_type,
				file_id=record.alias,
				file_size=record.file_size,
				tabfile_name=record.tabfile_name,
				inline_text_preview=record.inline_text_preview,
			)
			dirty = True
		if dirty:
			doc.save(ignore_permissions=True)

	# ---- helpers ------------------------------------------------------------

	def _update_metadata(
		self,
		alias: str,
		*,
		mime_type: str,
		file_size: int | None,
		inline_text_preview: str,
	) -> None:
		record = self._by_alias.get(alias)
		if record is None:
			return
		if mime_type and not record.mime_type:
			record.mime_type = mime_type
		if file_size and not record.file_size:
			record.file_size = file_size
		if inline_text_preview and len(inline_text_preview) > len(record.inline_text_preview):
			record.inline_text_preview = inline_text_preview


# ---------------------------------------------------------------------------
# Per-request cache helpers
# ---------------------------------------------------------------------------


def get_registry(conversation_id: str) -> FileAliasRegistry:
	"""Return a request-scoped registry for *conversation_id*.

	Caches on ``frappe.flags.file_alias_registry`` so repeated tool calls
	within a single request reuse the same instance — the registry is a
	mutable bidirectional map and we want every tool to see updates from
	earlier tools in the loop.
	"""

	try:
		import frappe
	except ImportError:
		# Tests / scripts: just build one without caching.
		return FileAliasRegistry.load(conversation_id)

	flags: Any = frappe.flags
	cache: dict[str, FileAliasRegistry] | None = getattr(flags, "file_alias_registry", None)
	if cache is None:
		cache = {}
		flags.file_alias_registry = cache

	registry = cache.get(conversation_id)
	if registry is None:
		registry = FileAliasRegistry.load(conversation_id)
		cache[conversation_id] = registry
	return registry


def clear_request_cache() -> None:
	"""Drop the per-request registry cache (test / shutdown helper)."""

	try:
		import frappe
	except ImportError:
		return
	if hasattr(frappe.flags, "file_alias_registry"):
		try:
			delattr(frappe.flags, "file_alias_registry")
		except Exception:
			frappe.flags.file_alias_registry = None


def _enforce_file_access(record: AttachmentRecord) -> None:
	"""Phase 27 §27.3 — run :func:`check_file_access` for *record*.

	Skipped silently when ``frappe`` is unavailable (pure-mode tests)
	or when no backing File row can be located — in that case the
	existing path-level guards remain the only line of defence.
	"""

	try:
		import frappe
	except ImportError:
		return

	# Phase 23 envelope flag — administrators / scheduled jobs run with
	# ignore_permissions when needed; respect that here so background
	# extractions are not blocked by the new check.
	if getattr(frappe.flags, "ignore_permissions", False):
		return

	try:
		from idp.core.security import check_file_access
	except Exception as exc:  # pragma: no cover — defensive
		logger.debug(f"_enforce_file_access: import failed ({exc})")
		return

	file_doc = _locate_file_doc(record)
	if file_doc is None:
		# Without a backing File row we can only fall back to the URL
		# guard which has already run by this point.  Log and continue.
		logger.debug(
			f"_enforce_file_access: no File doc for alias {record.alias!r} "
			f"(tabfile={record.tabfile_name!r}, url={record.file_url!r})"
		)
		return

	check_file_access(file_doc)


def _locate_file_doc(record: AttachmentRecord):
	"""Best-effort lookup of the ``tabFile`` doc behind *record*.

	Tries the persisted ``tabfile_name`` first (always unique), then
	falls back to a ``file_url`` lookup.  Returns ``None`` when neither
	hits — common during tests that build a registry by hand.
	"""

	try:
		import frappe
	except ImportError:
		return None

	if record.tabfile_name:
		try:
			return frappe.get_doc("File", record.tabfile_name)
		except Exception:
			pass

	if record.file_url:
		try:
			name = frappe.db.get_value("File", {"file_url": record.file_url}, "name")
			if name:
				return frappe.get_doc("File", name)
		except Exception:
			return None
	return None


def _alias_sort_key(alias: str) -> tuple[int, str]:
	"""Sort aliases by their numeric suffix (``file_2`` < ``file_10``)."""

	if alias.startswith(ALIAS_PREFIX):
		tail = alias[len(ALIAS_PREFIX) :]
		if tail.isdigit():
			return (0, f"{int(tail):010d}")
	return (1, alias)


__all__ = [
	"ALIAS_PREFIX",
	"AttachmentRecord",
	"FileAliasRegistry",
	"clear_request_cache",
	"get_registry",
]
