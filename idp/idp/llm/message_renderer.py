# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Render IDP Message rows + attachments into LLM-ready messages (Phase 18).

The renderer's job is to translate persisted :class:`IDPMessage` rows
(plus the per-conversation :class:`FileAliasRegistry`) into the dict
shapes accepted by :meth:`LLMClient.chat`:

* User messages with non-image attachments grow inline text dumps,
  page-delimited with ``--- Page N ---`` headers so the LLM can refer
  to "the supplier on page 1" without structured output.
* User messages with image attachments are upgraded into the
  multi-content-block form (``[{"type":"text"…}, {"type":"image_url"…}]``)
  so vision-capable providers get the image through the right channel
  while non-vision ones still see the text tag.
* The real ``file_url`` never leaks into the rendered message — only
  the alias does — so the LLM cannot hallucinate it.

The page-divider convention matches
``frappe_assistant_core.plugins.data_science.tools.extract_file_content.ExtractFileContent``
so downstream tooling that already consumes that format keeps working.
"""

from __future__ import annotations

import json
from typing import Any

from idp.core.logger import get_logger
from idp.idp.llm.file_alias import AttachmentRecord, FileAliasRegistry

logger = get_logger("idp.llm.renderer")

INLINE_TEXT_BUDGET = 15_000  # chars
PAGE_DIVIDER_RE_PREFIX = "--- Page "

# MIME → short tag map (matches ExtractFileContent.file_info.type).
_MIME_TAG = {
	"application/pdf": "pdf",
	"image/png": "image",
	"image/jpeg": "image",
	"image/jpg": "image",
	"image/webp": "image",
	"image/gif": "image",
	"image/heic": "image",
	"application/vnd.ms-excel": "excel",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
	"text/csv": "csv",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
	"application/msword": "docx",
	"text/plain": "text",
}

# Extensions used as fallback when the MIME string is missing or generic.
_EXT_TAG = {
	".pdf": "pdf",
	".png": "image",
	".jpg": "image",
	".jpeg": "image",
	".webp": "image",
	".gif": "image",
	".heic": "image",
	".xls": "excel",
	".xlsx": "excel",
	".csv": "csv",
	".doc": "docx",
	".docx": "docx",
	".txt": "text",
}


def short_mime_tag(mime_type: str | None, file_name: str | None = None) -> str:
	"""Return the short tag (``pdf``, ``image``, ``excel``, …) for a file.

	Falls back to the file extension when MIME is missing or generic.
	"""

	if mime_type:
		tag = _MIME_TAG.get(mime_type.lower())
		if tag:
			return tag
		if mime_type.startswith("image/"):
			return "image"
	if file_name:
		dot = file_name.rfind(".")
		if dot >= 0:
			ext = file_name[dot:].lower()
			tag = _EXT_TAG.get(ext)
			if tag:
				return tag
	return "file"


def is_image(record: AttachmentRecord) -> bool:
	"""True when *record* should be rendered as a vision content block."""

	return short_mime_tag(record.mime_type, record.file_name) == "image"


# ---------------------------------------------------------------------------
# Tag rendering
# ---------------------------------------------------------------------------


def render_image_tag(record: AttachmentRecord) -> str:
	"""``[Attached image: invoice.pdf, file_id: file_1]``"""

	return f"[Attached image: {record.file_name}, file_id: {record.alias}]"


def render_file_tag(
	record: AttachmentRecord,
	*,
	pages: int | None = None,
	extracted_pages: int | None = None,
) -> str:
	"""``[Attached file: invoice.pdf (pdf), file_id: file_1, pages: 3, extracted_pages: 3]``"""

	tag = short_mime_tag(record.mime_type, record.file_name)
	parts = [f"file_id: {record.alias}"]
	if pages is not None:
		parts.append(f"pages: {pages}")
	if extracted_pages is not None:
		parts.append(f"extracted_pages: {extracted_pages}")
	suffix = ", " + ", ".join(parts)
	return f"[Attached file: {record.file_name} ({tag}){suffix}]"


def render_attachment_for_llm(
	record: AttachmentRecord,
	*,
	extracted_text: str | None = None,
	pages: int | None = None,
	extracted_pages: int | None = None,
	budget: int = INLINE_TEXT_BUDGET,
) -> str:
	"""Return the text block placed in a user message for *record*.

	* For images, only the metadata tag is emitted; the bytes go through
	  the vision channel via :func:`render_user_message`.
	* For everything else, the metadata tag is followed by the inline
	  extract, page-delimited if the extract already contains
	  ``--- Page N ---`` markers.  The inline text is truncated at
	  ``budget`` characters and a tail marker advertises the
	  ``read_attachment_more`` tool when truncation occurs.
	"""

	if is_image(record):
		return render_image_tag(record)

	tag = render_file_tag(record, pages=pages, extracted_pages=extracted_pages)
	body = extracted_text if extracted_text is not None else record.inline_text_preview
	if not body:
		return tag

	full_len = len(body)
	rendered, truncated_chars = _truncate_to_budget(body, budget)
	header = f"--- Extracted content (first {min(full_len, budget)} chars) ---"
	parts = [tag, header, rendered]
	if truncated_chars > 0:
		parts.append(
			f"... [truncated: {truncated_chars} more chars available — use read_attachment_more tool]"
		)
	parts.append("---")
	return "\n".join(parts)


# ---------------------------------------------------------------------------
# Message rendering
# ---------------------------------------------------------------------------


def render_user_message(
	*,
	content: str,
	attachments: list[AttachmentRecord],
	registry: FileAliasRegistry | None = None,
	supports_vision: bool = False,
	extracts: dict[str, str] | None = None,
	pages: dict[str, int] | None = None,
) -> dict:
	"""Render a single user-role message dict for :meth:`LLMClient.chat`.

	When ``supports_vision`` is true and any attachment is an image, the
	resulting ``content`` is a list of content blocks (text + image_url)
	matching the OpenAI / Anthropic multimodal envelope.  Otherwise the
	message degrades to a plain string.

	Parameters
	----------
	content
	    The user's natural-language text.
	attachments
	    Records resolved from the registry (callers should look these up
	    via ``registry.resolve(alias)`` rather than ad-hoc dicts).
	supports_vision
	    Set from :meth:`LLMClient.supports`.  Drives whether image bytes
	    are emitted.
	extracts
	    Optional ``{alias: extracted_text}`` map overriding the per-record
	    ``inline_text_preview``.  Used when a tool re-extracted a file
	    with a different OCR config.
	pages
	    Optional ``{alias: page_count}`` map for non-image files.
	"""

	extracts = extracts or {}
	pages = pages or {}

	non_image_blocks: list[str] = []
	image_blocks: list[dict] = []
	for record in attachments:
		if is_image(record):
			if supports_vision:
				img_block = _build_image_block(record)
				if img_block:
					image_blocks.append(img_block)
			# Always emit the text tag too — non-vision providers need it
			# and even vision ones benefit from the alias being in text.
			non_image_blocks.append(render_image_tag(record))
		else:
			non_image_blocks.append(
				render_attachment_for_llm(
					record,
					extracted_text=extracts.get(record.alias),
					pages=pages.get(record.alias),
				)
			)

	text_parts: list[str] = []
	if content:
		text_parts.append(content)
	text_parts.extend(non_image_blocks)
	text = "\n\n".join(p for p in text_parts if p)

	if supports_vision and image_blocks:
		blocks: list[dict] = []
		if text:
			blocks.append({"type": "text", "text": text})
		blocks.extend(image_blocks)
		return {"role": "user", "content": blocks}

	return {"role": "user", "content": text}


def render_history(
	messages: list[dict],
	registry: FileAliasRegistry,
	*,
	supports_vision: bool = False,
) -> list[dict]:
	"""Render a list of persisted message dicts into LLM-ready dicts.

	Each element of ``messages`` is expected to follow the
	``IDPMessage.as_dict()`` shape — i.e. it has at least ``role``,
	``content`` and an optional JSON-encoded ``attachments`` list of
	``{file_id, file_url, file_name, mime_type}`` items.

	System / assistant / tool messages pass through with minimal change;
	user messages get the full attachment-rendering treatment.
	"""

	rendered: list[dict] = []
	for raw in messages:
		role = raw.get("role")
		if role == "user":
			attachments = _resolve_attachments(raw.get("attachments"), registry)
			rendered.append(
				render_user_message(
					content=raw.get("content") or "",
					attachments=attachments,
					registry=registry,
					supports_vision=supports_vision,
				)
			)
			continue

		if role == "assistant":
			msg: dict[str, Any] = {"role": "assistant", "content": raw.get("content") or ""}
			# Prefer the full tool_calls array (multi-tool-call turns) so
			# every tool_use_id round-trips intact and matches its tool_result
			# block.  Fall back to the legacy single tool_call_id/name fields
			# for rows persisted before the tool_calls field was added.
			calls_raw = raw.get("tool_calls")
			if isinstance(calls_raw, list) and calls_raw:
				msg["tool_calls"] = [
					{
						"id": c.get("id") or c.get("call_id") or "",
						"type": "function",
						"function": {
							"name": c.get("name") or "",
							"arguments": _to_json(c.get("arguments")),
						},
					}
					for c in calls_raw
					if isinstance(c, dict) and (c.get("id") or c.get("call_id"))
				]
			elif raw.get("tool_call_id") and raw.get("tool_name"):
				msg["tool_calls"] = [
					{
						"id": raw["tool_call_id"],
						"type": "function",
						"function": {
							"name": raw["tool_name"],
							"arguments": _to_json(raw.get("tool_arguments")),
						},
					}
				]
			rendered.append(msg)
			continue

		if role == "tool":
			# Anthropic (and OpenAI strict mode) reject ``tool_result`` /
			# ``tool`` messages whose ``tool_call_id`` is empty or doesn't
			# match the upstream assistant ``tool_use``.  We silently
			# downgrade orphan rows (e.g. legacy ``user_confirmation``
			# acks persisted before Phase 24) to plain user-role text so
			# the LLM still sees the content but the API stays happy.
			tool_call_id = raw.get("tool_call_id") or ""
			content_str = _to_json(raw.get("tool_result")) or (raw.get("content") or "")
			if not tool_call_id:
				rendered.append({"role": "user", "content": content_str})
				continue
			rendered.append(
				{
					"role": "tool",
					"tool_call_id": tool_call_id,
					"content": content_str,
				}
			)
			continue

		# system / fallback
		rendered.append({"role": role or "system", "content": raw.get("content") or ""})

	return rendered


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_attachments(raw: Any, registry: FileAliasRegistry) -> list[AttachmentRecord]:
	"""Translate an IDPMessage.attachments JSON list into records.

	Unknown aliases are skipped silently — :func:`resolve_or_stop` is the
	right hook for hard-fail semantics, but during plain rendering we
	prefer to surface what we can.
	"""

	if raw is None:
		return []
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except ValueError:
			return []
	if not isinstance(raw, list):
		return []

	out: list[AttachmentRecord] = []
	for entry in raw:
		if not isinstance(entry, dict):
			continue
		alias = entry.get("file_id") or entry.get("alias")
		record: AttachmentRecord | None = None
		if alias:
			record = registry.resolve(alias)
		if record is None and entry.get("file_url"):
			# Persisted message survived a registry rebuild; re-register
			# so the alias stays consistent across renders.
			alias = registry.register(
				file_url=entry["file_url"],
				file_name=entry.get("file_name") or "",
				mime_type=entry.get("mime_type") or "",
				tabfile_name=entry.get("tabfile_name"),
			)
			record = registry.resolve(alias)
		if record is not None:
			out.append(record)
	return out


def _truncate_to_budget(body: str, budget: int) -> tuple[str, int]:
	"""Truncate *body* to *budget* chars, preferring page boundaries.

	Returns ``(rendered, truncated_chars)``.  If the body fits, returns
	``(body, 0)`` unchanged.
	"""

	if len(body) <= budget:
		return body, 0

	cut = body.rfind(PAGE_DIVIDER_RE_PREFIX, 0, budget)
	if cut <= 0:
		cut = budget
	rendered = body[:cut].rstrip()
	return rendered, len(body) - cut


def _build_image_block(record: AttachmentRecord) -> dict | None:
	"""Return the ``image_url`` content block for *record*.

	Reads the file via Frappe and base64-encodes it.  Returns ``None``
	if the bytes cannot be retrieved — callers fall back to the text
	tag in that case.
	"""

	try:
		import base64

		import frappe
	except ImportError:
		return None

	try:
		fdoc = frappe.get_doc("File", {"file_url": record.file_url})
		path = fdoc.get_full_path()
		with open(path, "rb") as fh:
			data = fh.read()
	except Exception as exc:
		logger.warning(f"cannot inline image {record.alias} ({record.file_url}): {exc}")
		return None

	mime = record.mime_type or "image/png"
	encoded = base64.b64encode(data).decode("ascii")
	return {
		"type": "image_url",
		"image_url": {"url": f"data:{mime};base64,{encoded}"},
	}


def _to_json(value: Any) -> str:
	"""JSON-encode *value*; pass strings through unchanged."""

	if value is None:
		return ""
	if isinstance(value, str):
		return value
	try:
		return json.dumps(value, default=str, ensure_ascii=False)
	except (TypeError, ValueError):
		return str(value)


__all__ = [
	"INLINE_TEXT_BUDGET",
	"is_image",
	"render_attachment_for_llm",
	"render_file_tag",
	"render_history",
	"render_image_tag",
	"render_user_message",
	"short_mime_tag",
]
