# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Compatibility shim — ``read_attachment_more`` is no longer an LLM-exposed tool.

Paginated attachment reading is now handled by ``extract_document`` with
an ``offset`` parameter.  This module is retained so any Python code that
imports ``read_attachment_more`` directly is not broken.
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult
from idp.tools.extract_document import _paginate


def read_attachment_more(arguments: dict, ctx: ToolContext) -> ToolResult:
	"""Fetch additional extracted text from an attachment at a given offset.

	Kept as a Python-callable shim.  No longer registered as an LLM tool
	— use extract_document with offset=N instead.
	"""
	args = arguments or {}
	alias = (args.get("file_id") or "").strip()
	if not alias:
		return ToolResult.fail("file_id is required", error_code="MISSING_ARGUMENT", stop_processing=True)

	try:
		offset = int(args.get("offset", 0))
	except (TypeError, ValueError):
		return ToolResult.fail("offset must be an integer", error_code="MISSING_ARGUMENT", stop_processing=True)
	if offset < 0:
		offset = 0

	return _paginate(alias, offset, args, ctx)


__all__ = ["read_attachment_more"]
