# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Compatibility shim — ``create_master`` is no longer an LLM-exposed tool.

Master creation is now handled by ``resolve_masters(mode='create')``.
This module is retained so any Python code that imports ``create_master``
directly is not broken.
"""

from __future__ import annotations

from idp.tools.base import ToolContext, ToolResult
from idp.tools.resolve_masters import _create as _resolve_create


def create_master(arguments: dict, ctx: ToolContext) -> ToolResult:
	"""Create a missing master record.

	Kept as a Python-callable shim.  No longer registered as an LLM tool
	— use resolve_masters(mode='create') instead.
	"""
	return _resolve_create(arguments or {}, ctx)


__all__ = ["create_master"]
