# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Tool spec dataclass, response envelope, and the ``@tool`` decorator (Phase 19).

A *tool* is the bridge between an LLM tool-call (``ToolCall``) and a
server-side handler.  Every tool publishes:

* a JSON-Schema for its arguments (consumed by the LLM provider),
* a server-side handler that returns a uniform :class:`ToolResult`
  envelope (success / error / stop_processing / optional card),
* metadata flags — ``mutating`` (requires user confirmation) and
  ``requires_role`` (role gate enforced by the agent loop).

The envelope is deliberately uniform across all tools so the agent
loop and the chatbot UI can treat every result identically.  The
``stop_processing`` flag is the contract that lets a tool abort the
agent loop on fatal conditions (file alias not found, permission
denied, budget exceeded, ERPNext insert failure) without the LLM
inventing a recovery path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
	"""Uniform result envelope returned by every tool handler.

	Mirrors the wire-format documented in roadmap §19.3.  ``to_dict``
	produces the JSON-serialisable shape the agent loop hands back to
	the LLM and persists on the ``IDP Message`` row.
	"""

	success: bool
	data: dict | None = None
	error: str | None = None
	error_code: str | None = None
	stop_processing: bool = False
	card: dict | None = None

	def to_dict(self) -> dict:
		return {
			"success": self.success,
			"data": self.data,
			"error": self.error,
			"error_code": self.error_code,
			"stop_processing": self.stop_processing,
			"card": self.card,
		}

	# ------------------------------------------------------------------ helpers

	@classmethod
	def ok(cls, data: dict | None = None, *, card: dict | None = None) -> "ToolResult":
		return cls(success=True, data=data, card=card)

	@classmethod
	def fail(
		cls,
		error: str,
		*,
		error_code: str | None = None,
		stop_processing: bool = False,
		card: dict | None = None,
	) -> "ToolResult":
		return cls(
			success=False,
			error=error,
			error_code=error_code,
			stop_processing=stop_processing,
			card=card,
		)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
	"""Per-call context passed to every tool handler.

	Tools should never reach into ``frappe.session`` directly — the
	agent loop builds a context once per iteration and threads it
	through the dispatcher so unit tests can inject stubs.
	"""

	conversation_id: str
	user: str
	company: str | None = None
	output_language: str = "English"
	target_doctype: str | None = None
	# Phase 22 — PaddleOCR language code applied to the source document
	# (``"en"``, ``"hi"``, ``"ar"``, ...).  ``None`` means "fall back to
	# IDP Settings.default_ocr_language".  Tools that map fields use this
	# to pull multilingual keyword aliases from
	# :mod:`idp.idp.mappers.keywords_ml`.
	ocr_language: str | None = None
	# Free-form bag for caller hints (e.g. force_llm_review=True).
	extras: dict = field(default_factory=dict)


@dataclass
class ToolSpec:
	"""A registered tool entry."""

	name: str
	description: str
	parameters_schema: dict
	handler: Callable[..., ToolResult]
	requires_role: str | None = None
	mutating: bool = False

	def to_provider_schema(self) -> dict:
		"""Return the OpenAI-style ``{"type":"function", "function": {...}}``
		envelope expected by :meth:`LLMClient.chat`.
		"""

		return {
			"type": "function",
			"function": {
				"name": self.name,
				"description": self.description,
				"parameters": self.parameters_schema,
			},
		}


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tool(
	*,
	name: str,
	description: str,
	parameters_schema: dict,
	requires_role: str | None = None,
	mutating: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., ToolResult]]:
	"""Register *handler* as a tool under *name*.

	The decorator does **not** wrap the handler — it only registers it
	so the function can still be unit-tested directly without going
	through the dispatcher.
	"""

	from idp.idp.llm.tools.registry import register_tool

	def decorator(handler: Callable[..., Any]) -> Callable[..., ToolResult]:
		spec = ToolSpec(
			name=name,
			description=description,
			parameters_schema=parameters_schema,
			handler=handler,
			requires_role=requires_role,
			mutating=mutating,
		)
		register_tool(spec)
		return handler

	return decorator


__all__ = [
	"ToolContext",
	"ToolResult",
	"ToolSpec",
	"tool",
]
