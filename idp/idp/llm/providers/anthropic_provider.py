# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Anthropic Messages-API adapter.

Soft-imports the ``anthropic`` SDK.  The adapter translates the
OpenAI-shaped tool envelope coming in from the rest of the app into
Anthropic's ``input_schema`` format, and unwraps ``tool_use`` content
blocks back into :class:`ToolCall` objects.
"""

from __future__ import annotations

from typing import Any

from idp.core.exceptions import LLMProviderUnavailableError, LLMResponseParseError
from idp.core.logger import get_logger
from idp.idp.llm.providers.base import LLMProvider, LLMResponse, TokenUsage, ToolCall
from idp.idp.llm.providers.registry import register_provider

logger = get_logger("idp.llm.anthropic")


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


@register_provider("anthropic")
class AnthropicProvider(LLMProvider):
	"""Adapter for Anthropic's Messages API."""

	def __init__(
		self,
		*,
		api_key: str | None = None,
		default_model: str = "claude-haiku-4-5-20251101",
		**_: Any,
	) -> None:
		self.api_key = api_key
		self.default_model = default_model
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
		**extra: Any,
	) -> LLMResponse:
		if stream:
			logger.debug("stream=True requested but sync path used for Phase 16")

		client = self._get_client()
		system, chat = split_system_and_messages(messages)
		payload: dict[str, Any] = {
			"model": model or self.default_model,
			"messages": chat,
			"max_tokens": max_tokens,
			"temperature": temperature,
		}
		if system:
			payload["system"] = system
		if tools:
			payload["tools"] = translate_tools_openai_to_anthropic(tools)
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
