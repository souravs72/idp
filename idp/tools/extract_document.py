# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``extract_document`` — extract structured content from a file alias (Phase 19).

Returns the canonical envelope documented in roadmap §19.3.1, with the
four deviations from frappe_assistant_core's ``ExtractFileContent``:

1. ``file_info.file_id`` is the monotonic Phase-18 alias (``file_1``)
   rather than the 10-char ``tabFile`` hash.
2. ``file_info.url`` is omitted — the real URL stays server-side in
   :class:`FileAliasRegistry`.
3. ``tables`` is added (PP-Structure 2-D arrays).
4. ``confidence`` / ``language`` are added.

A failed extraction returns ``stop_processing=True`` with a
machine-readable ``error_code`` so the agent loop halts immediately.
"""

from __future__ import annotations

from typing import Any

from idp.core.logger import get_logger
from idp.llm.file_alias import get_registry
from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

logger = get_logger("idp.tools.extract_document")

# Hard fallback used when IDP Settings has no value yet (Phase 27 §27.5
# surfaces ``inline_text_budget_chars`` as a configurable cap).
_DEFAULT_INLINE_TEXT_BUDGET = 15_000


def _inline_text_budget() -> int:
	"""Read the configured budget; fall back to the legacy hard-coded value."""

	try:
		from idp.core.config import get_inline_text_budget_chars

		return get_inline_text_budget_chars()
	except Exception:
		return _DEFAULT_INLINE_TEXT_BUDGET
SHORT_TYPE_BY_MIME = {
	"application/pdf": "pdf",
	"image/png": "image",
	"image/jpeg": "image",
	"image/jpg": "image",
	"image/tiff": "image",
	"image/webp": "image",
	"application/vnd.ms-excel": "excel",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
	"text/csv": "csv",
	"application/csv": "csv",
	"application/msword": "docx",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
	"text/plain": "text",
}


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"file_id": {
			"type": "string",
			"description": (
				"Monotonic alias from the attachment tag (e.g. 'file_1'). Never a tabFile hash or URL."
			),
		},
		"language": {
			"type": "string",
			"description": "OCR language hint (ISO-639-1, e.g. 'en'). Defaults to 'en'.",
		},
	},
	"required": ["file_id"],
	"additionalProperties": False,
}


@tool(
	name="extract_document",
	description=(
		"Extract structured content (text + tables + metadata) from a file the "
		"user has attached.  Reference the file by its monotonic file_id alias "
		"(e.g. 'file_1') — never a URL or hash.  Returns page-delimited text, "
		"detected tables, and per-page extraction stats.  On failure returns "
		"stop_processing=true with an error_code; do not retry."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def extract_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	"""Resolve the alias, dispatch to the format-appropriate extractor."""

	alias = (arguments or {}).get("file_id", "").strip()
	if not alias:
		return ToolResult.fail(
			"file_id is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=True,
		)

	lang = (arguments.get("language") or "en").strip() or "en"

	registry = get_registry(ctx.conversation_id)
	try:
		record = registry.resolve(alias)
	except Exception as exc:
		# Phase 27 §27.3 — IDPPermissionError carries an error_code in
		# its ``code`` attribute; surface it as a stop_processing envelope
		# so the agent loop halts cleanly instead of speculatively
		# retrying with a different alias.
		from idp.core.exceptions import IDPPermissionError

		if isinstance(exc, IDPPermissionError):
			return ToolResult.fail(
				str(exc) or "Permission denied for this attachment.",
				error_code=exc.code,
				stop_processing=True,
			)
		raise
	if record is None:
		return ToolResult.fail(
			f"unknown file alias: {alias!r}",
			error_code="FILE_ALIAS_NOT_FOUND",
			stop_processing=True,
		)

	# Extraction.
	try:
		from idp.extractors import extract_content
	except ImportError as exc:
		return ToolResult.fail(
			f"extractor pipeline unavailable: {exc}",
			error_code="EXTRACTION_FAILED",
			stop_processing=True,
		)

	# Phase 30 §27.6 — surface a human-readable progress message before
	# the (potentially slow) extractor runs.  ``Reading <file>…`` mirrors
	# the wording the roadmap suggests for the live progress banner.
	publish_progress(
		ctx,
		tool_name="extract_document",
		user_visible_message=f"Reading {record.file_name or alias}…",
		stage="extract_start",
	)

	try:
		result = extract_content(record.file_url, lang=lang)
	except Exception as exc:
		# Re-raise so the dispatcher can map it to the right error_code.
		raise exc

	publish_progress(
		ctx,
		tool_name="extract_document",
		user_visible_message=(
			f"Read {int((result.metadata or {}).get('extracted_pages') or (result.metadata or {}).get('page_count') or 1)} page(s); analysing…"
		),
		stage="extract_done",
	)

	body = (result.text or "").strip()
	full_len = len(body)
	budget = _inline_text_budget()
	truncated = full_len > budget
	if truncated:
		body = _truncate_to_page_boundary(body, budget)

	# Refresh the registry preview so future tools see the larger sample.
	registry.register(
		file_url=record.file_url,
		file_name=record.file_name,
		mime_type=record.mime_type,
		tabfile_name=record.tabfile_name,
		file_size=record.file_size,
		inline_text_preview=body[: min(len(body), 4_000)],
	)

	metadata: dict[str, Any] = result.metadata or {}
	pages = int(metadata.get("page_count") or metadata.get("pages") or 1)
	extracted_pages = int(metadata.get("extracted_pages") or pages)

	short_type = SHORT_TYPE_BY_MIME.get(
		record.mime_type or metadata.get("mime_type", ""),
		_short_type_fallback(record.file_name),
	)

	envelope = {
		"content": body,
		"tables": _normalise_tables(result.tables or []),
		"pages": pages,
		"extracted_pages": extracted_pages,
		"truncated": truncated,
		"file_info": {
			"file_id": alias,
			"file_name": record.file_name,
			"type": short_type,
			"size": record.file_size or metadata.get("file_size"),
			"confidence": result.confidence,
			"language": metadata.get("language") or lang,
			"currency": metadata.get("currency") or _default_currency(ctx),
		},
	}
	return ToolResult.ok(data=envelope)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_tables(tables: Any) -> Any:
	"""Tables may arrive as list[list[list[str]]] (positional) or the dict
	shape shown in the roadmap.  We pass the positional form through and
	wrap a bare list-of-2D under a generic ``items`` key only when the
	first cell looks like an item header.
	"""

	if not tables:
		return []
	# Already a dict — trust the extractor.
	if isinstance(tables, dict):
		return tables
	# List of 2-D arrays — keep as-is so the LLM can address them by index.
	return tables


def _short_type_fallback(file_name: str) -> str:
	name = (file_name or "").lower()
	for ext, short in (
		(".pdf", "pdf"),
		(".png", "image"),
		(".jpg", "image"),
		(".jpeg", "image"),
		(".tiff", "image"),
		(".webp", "image"),
		(".xlsx", "excel"),
		(".xls", "excel"),
		(".csv", "csv"),
		(".docx", "docx"),
		(".doc", "docx"),
	):
		if name.endswith(ext):
			return short
	return "file"


def _default_currency(ctx: ToolContext) -> str:
	"""Best-effort default currency: company currency, then USD."""

	if ctx.company:
		try:
			import frappe

			val = frappe.db.get_value("Company", ctx.company, "default_currency")
			if val:
				return str(val)
		except Exception:
			pass
	return "USD"


def _truncate_to_page_boundary(body: str, budget: int) -> str:
	"""Truncate to *budget* preferring a ``--- Page `` marker boundary."""

	if len(body) <= budget:
		return body
	cut = body.rfind("--- Page ", 0, budget)
	if cut > budget // 2:
		return body[:cut].rstrip()
	return body[:budget].rstrip()


__all__ = ["extract_document"]
