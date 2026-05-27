# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Compatibility shim — ``list_missing_masters`` is no longer an LLM-exposed tool.

Missing-master inspection is now handled by ``resolve_masters(mode='report')``.
This module is retained so any Python code that imports ``list_missing_masters``
directly is not broken.
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult
from idp.tools.resolve_masters import _report as _resolve_report


def list_missing_masters(arguments: dict, ctx: ToolContext) -> ToolResult:
	"""Inspect a proposed mapping and return missing master records.

	Kept as a Python-callable shim.  No longer registered as an LLM tool
	— use resolve_masters(mode='report') instead.
	"""
	return _resolve_report(arguments or {}, ctx)


__all__ = ["list_missing_masters"]
