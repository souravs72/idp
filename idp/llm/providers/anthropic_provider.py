# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Anthropic Messages-API adapter.

Soft-imports the ``anthropic`` SDK.  The adapter translates the
OpenAI-shaped tool envelope coming in from the rest of the app into
Anthropic's ``input_schema`` format, and unwraps ``tool_use`` content
blocks back into :class:`ToolCall` objects.
"""

from __future__ import annotations

import json
from typing import Any

from idp.core.exceptions import LLMProviderUnavailableError, LLMResponseParseError
from idp.core.logger import get_logger
from idp.llm.providers.base import LLMProvider, LLMResponse, TokenUsage, ToolCall
from idp.llm.providers.registry import register_provider

logger = get_logger("idp.llm.anthropic")


_EPHEMERAL: dict[str, Any] = {"type": "ephemeral"}


def _wrap_system_with_cache(system: str) -> list[dict]:
	"""Wrap *system* text in an ephemeral cache block for prompt caching.

	Anthropic accepts ``system`` either as a string (no caching) or as a
	list of ``{"type":"text","text":..., "cache_control":...}`` blocks
	(cacheable).  Static system text marked ephemeral is cached for ~5
	minutes server-side, yielding ~90% discount on cached input tokens.
	"""

	return [{"type": "text", "text": system, "cache_control": _EPHEMERAL}]


def _wrap_tools_with_cache(tools: list[dict]) -> list[dict]:
	"""Attach ``cache_control: ephemeral`` to the LAST tool definition.

	Anthropic propagates cache scope from any single tool entry to the
	full ``tools`` block, so we only need to mark one — the last makes
	the cache boundary explicit and survives reordering by callers."""

	if not tools:
		return tools
	out = [dict(t) for t in tools]
	out[-1]["cache_control"] = _EPHEMERAL
	return out


def translate_tools_openai_to_anthropic(tools: list[dict] | None) -> list[dict]:
	"""Convert OpenAI-style ``{"type":"function","function":{...}}`` envelopes
	to Anthropic's ``{"name","description","input_schema"}`` shape."""

	if not tools:
		return []
	out: list[dict] = []
	for t in tools:
		fn = t.get("function") if t.get("type") == "function" else t
		if not isinstance(fn, dict):
			continue
		out.append(
			{
				"name": fn.get("name", ""),
				"description": fn.get("description", ""),
				"input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
			}
		)
	return out


def split_system_and_messages(messages: list[dict]) -> tuple[str, list[dict]]:
	"""Anthropic takes ``system`` as a top-level param, not a message role."""

	system_parts: list[str] = []
	chat: list[dict] = []
	for m in messages:
		if m.get("role") == "system":
			system_parts.append(str(m.get("content", "")))
		else:
			chat.append(m)
	return "\n\n".join(system_parts), chat


def _stringify_tool_result(content: Any) -> str:
	"""Serialise a tool result payload to a string for Anthropic's
	``tool_result.content`` field, which only accepts a string or
	a list of text/image blocks."""

	if content is None:
		return ""
	if isinstance(content, str):
		return content
	try:
		return json.dumps(content, default=str)
	except (TypeError, ValueError):
		return str(content)


def translate_messages_openai_to_anthropic(messages: list[dict]) -> list[dict]:
	"""Convert OpenAI-style chat history to Anthropic's Messages-API shape.

	Anthropic rejects ``role: "tool"`` outright and expects:

	* assistant tool calls as ``{"type":"tool_use", ...}`` blocks inside
	  an ``assistant`` message.
	* tool results as ``{"type":"tool_result", "tool_use_id": ..., ...}``
	  blocks inside a ``user`` message (consecutive results may be
	  merged into a single user message).

	System messages are expected to have already been split out by
	:func:`split_system_and_messages` before this is called.
	"""

	out: list[dict] = []
	for m in messages:
		role = m.get("role")
		content = m.get("content")

		if role == "tool":
			# OpenAI shape: {"role":"tool", "tool_call_id":..., "content":...}
			# Anthropic shape: a user message with a tool_result block.
			block = {
				"type": "tool_result",
				"tool_use_id": m.get("tool_call_id") or "",
				"content": _stringify_tool_result(content),
			}
			# Merge with the previous user message if it already contains
			# tool_result blocks — Anthropic prefers consecutive results
			# bundled together.
			if (
				out
				and out[-1].get("role") == "user"
				and isinstance(out[-1].get("content"), list)
				and out[-1]["content"]
				and isinstance(out[-1]["content"][0], dict)
				and out[-1]["content"][0].get("type") == "tool_result"
			):
				out[-1]["content"].append(block)
			else:
				out.append({"role": "user", "content": [block]})
			continue

		if role == "assistant":
			tool_calls = m.get("tool_calls") or []
			if not tool_calls:
				# Plain text assistant message — pass through.
				out.append({"role": "assistant", "content": content or ""})
				continue

			blocks: list[dict] = []
			text = content if isinstance(content, str) else ""
			if text:
				blocks.append({"type": "text", "text": text})
			for call in tool_calls:
				fn = call.get("function") or {}
				args_raw = fn.get("arguments")
				# OpenAI sends arguments as a JSON-encoded string; Anthropic
				# wants a parsed object under ``input``.
				if isinstance(args_raw, str):
					try:
						args_obj = json.loads(args_raw) if args_raw.strip() else {}
					except json.JSONDecodeError:
						args_obj = {"_raw": args_raw}
				elif isinstance(args_raw, dict):
					args_obj = args_raw
				else:
					args_obj = {}
				blocks.append(
					{
						"type": "tool_use",
						"id": call.get("id") or "",
						"name": fn.get("name") or "",
						"input": args_obj,
					}
				)
			out.append({"role": "assistant", "content": blocks})
			continue

		# user / fallback — pass through unchanged.  ``content`` may be a
		# string or a list of multimodal blocks (text/image), both of
		# which Anthropic accepts on a user message.
		out.append({"role": role or "user", "content": content if content is not None else ""})

	return out


@register_provider("anthropic")
class AnthropicProvider(LLMProvider):
	"""Adapter for Anthropic's Messages API."""

	def __init__(
		self,
		*,
		api_key: str | None = None,
		default_model: str = "claude-opus-4-5-20251101",
		cache_control: bool = True,
		**_: Any,
	) -> None:
		self.api_key = api_key
		self.default_model = default_model
		# Wraps system prompt + tool definitions in `cache_control: ephemeral`
		# so subsequent turns get the ~90% cached-token discount.  Static
		# prompts cache for ~5 minutes server-side at Anthropic.
		self.cache_control = bool(cache_control)
		self._client: Any = None

	def chat(
		self,
		messages: list[dict],
		*,
		tools: list[dict] | None = None,
		tool_choice: str | dict = "auto",
		response_format: dict | None = None,
		temperature: float = 0.0,
		max_tokens: int = 4_096,
		stream: bool = False,
		model: str | None = None,
		cache_control: bool | None = None,
		**extra: Any,
	) -> LLMResponse:
		if stream:
			logger.debug("stream=True requested but sync path used for Phase 16")

		client = self._get_client()
		system, chat = split_system_and_messages(messages)
		chat = translate_messages_openai_to_anthropic(chat)
		payload: dict[str, Any] = {
			"model": model or self.default_model,
			"messages": chat,
			"max_tokens": max_tokens,
			"temperature": temperature,
		}
		# Per-call override falls back to the instance default.  Callers
		# can pass cache_control=False for short one-off prompts where
		# caching overhead exceeds the discount.
		use_cache = self.cache_control if cache_control is None else bool(cache_control)
		if system:
			payload["system"] = _wrap_system_with_cache(system) if use_cache else system
		if tools:
			translated = translate_tools_openai_to_anthropic(tools)
			payload["tools"] = _wrap_tools_with_cache(translated) if use_cache else translated
			if isinstance(tool_choice, str) and tool_choice in {"auto", "any"}:
				payload["tool_choice"] = {"type": tool_choice}
		payload.update(extra)

		raw = client.messages.create(**payload)
		return self._normalise(raw, payload["model"])

	def count_tokens(self, messages: list[dict], *, model: str | None = None) -> int:
		# anthropic.count_tokens is available in newer SDKs; fall back to
		# the char/4 heuristic when unavailable.
		try:
			client = self._get_client()
			fn = getattr(client, "count_tokens", None)
			if callable(fn):
				text = "\n".join(str(m.get("content", "")) for m in messages)
				return int(fn(text))
		except Exception as exc:
			logger.debug(f"anthropic count_tokens fallback: {exc}")
		text = "\n".join(str(m.get("content", "")) for m in messages)
		return max(1, len(text) // 4)

	# ---- helpers ------------------------------------------------------------

	def _get_client(self) -> Any:
		if self._client is not None:
			return self._client
		try:
			import anthropic
		except ImportError as exc:
			raise LLMProviderUnavailableError(
				"anthropic SDK not installed; run `pip install anthropic` or install "
				"the `llm-anthropic` extra"
			) from exc
		kwargs: dict[str, Any] = {}
		if self.api_key:
			kwargs["api_key"] = self.api_key
		self._client = anthropic.Anthropic(**kwargs)
		return self._client

	def _normalise(self, raw: Any, model: str) -> LLMResponse:
		"""Translate an Anthropic SDK response into :class:`LLMResponse`."""

		try:
			data = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
		except Exception as exc:
			raise LLMResponseParseError(f"cannot decode Anthropic response: {exc}") from exc

		content_blocks = data.get("content") or []
		text_parts: list[str] = []
		tool_calls: list[ToolCall] = []
		for block in content_blocks:
			btype = block.get("type")
			if btype == "text":
				text_parts.append(block.get("text", ""))
			elif btype == "tool_use":
				tool_calls.append(
					ToolCall(
						name=block.get("name", ""),
						arguments=block.get("input") or {},
						call_id=block.get("id"),
					)
				)

		usage = data.get("usage") or {}
		# Anthropic returns cache stats as siblings of input/output tokens.
		# Surface them on the raw envelope so the Document Log can record
		# `cached_tokens` for §TE.8 measurement.
		cache_read = int(usage.get("cache_read_input_tokens") or 0)
		cache_created = int(usage.get("cache_creation_input_tokens") or 0)
		if cache_read or cache_created:
			data["_idp_cached_tokens"] = cache_read
			data["_idp_cache_creation_tokens"] = cache_created
		return LLMResponse(
			content="\n".join(text_parts) or None,
			tool_calls=tool_calls,
			finish_reason=data.get("stop_reason") or "stop",
			usage=TokenUsage(
				prompt=int(usage.get("input_tokens") or 0),
				completion=int(usage.get("output_tokens") or 0),
			),
			raw=data,
			model=model,
			provider="anthropic",
		)
