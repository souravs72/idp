# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``read_attachment_more`` — paginated access to truncated attachments.

The default rendering in :mod:`idp.llm.message_renderer` caps
inline content at ``INLINE_TEXT_BUDGET`` (15 000 chars).  This tool
lets the LLM ask for the next slice when the truncation marker
indicates more bytes are available.

The implementation re-runs extraction (extractors are deterministic
for the same file) and slices the result.  Future optimisation:
cache the full extraction on the conversation row.
"""

from __future__ import annotations

from idp.llm.file_alias import get_registry
from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

DEFAULT_CHUNK = 10_000
MAX_CHUNK = 30_000


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"file_id": {"type": "string", "description": "Monotonic alias (e.g. 'file_1')."},
		"offset": {
			"type": "integer",
			"minimum": 0,
			"description": "Byte offset (in characters) into the extracted text to start from.",
		},
		"length": {
			"type": "integer",
			"minimum": 1,
			"maximum": MAX_CHUNK,
			"description": f"Maximum chars to return (default {DEFAULT_CHUNK}).",
		},
	},
	"required": ["file_id", "offset"],
	"additionalProperties": False,
}


@tool(
	name="read_attachment_more",
	description=(
		"Fetch additional extracted text from an attachment after the inline "
		"15K-char preview was truncated.  Specify the file_id alias and the "
		"character offset to resume from."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def read_attachment_more(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	alias = (args.get("file_id") or "").strip()
	if not alias:
		return ToolResult.fail("file_id is required", error_code="MISSING_ARGUMENT", stop_processing=True)

	try:
		offset = int(args.get("offset", 0))
	except (TypeError, ValueError):
		return ToolResult.fail(
			"offset must be an integer",
			error_code="MISSING_ARGUMENT",
			stop_processing=True,
		)
	if offset < 0:
		offset = 0

	length = args.get("length")
	try:
		length = int(length) if length is not None else DEFAULT_CHUNK
	except (TypeError, ValueError):
		length = DEFAULT_CHUNK
	length = max(1, min(length, MAX_CHUNK))

	registry = get_registry(ctx.conversation_id)
	record = registry.resolve(alias)
	if record is None:
		return ToolResult.fail(
			f"unknown file alias: {alias!r}",
			error_code="FILE_ALIAS_NOT_FOUND",
			stop_processing=True,
		)

	try:
		from idp.extractors import extract_content
	except ImportError as exc:
		return ToolResult.fail(
			f"extractor pipeline unavailable: {exc}",
			error_code="EXTRACTION_FAILED",
			stop_processing=True,
		)

	publish_progress(
		ctx,
		tool_name="read_attachment_more",
		user_visible_message=(
			f"Reading more of {record.file_name or alias} from offset {offset}…"
		),
		stage="read_more_start",
	)

	result = extract_content(record.file_url, lang="en")
	body = result.text or ""
	total = len(body)
	chunk = body[offset : offset + length]
	next_offset = offset + len(chunk)
	return ToolResult.ok(
		data={
			"file_id": alias,
			"offset": offset,
			"length": len(chunk),
			"content": chunk,
			"total_chars": total,
			"next_offset": next_offset if next_offset < total else None,
			"truncated": next_offset < total,
		}
	)


__all__ = ["read_attachment_more"]
