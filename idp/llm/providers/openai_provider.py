# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""OpenAI chat-completion adapter.

Soft-imports the ``openai`` SDK so this module loads even when the
optional dependency is absent — the SDK is only required at ``chat()``
call time.  Tool-calling, JSON mode and vision are delegated through to
the SDK; the adapter normalises the response into :class:`LLMResponse`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from idp.core.exceptions import LLMProviderUnavailableError, LLMResponseParseError
from idp.core.logger import get_logger
from idp.llm.providers.base import (
	LLMProvider,
	LLMResponse,
	StreamDelta,
	TokenUsage,
	ToolCall,
)
from idp.llm.providers.registry import register_provider

logger = get_logger("idp.llm.openai")


@register_provider("openai")
class OpenAIProvider(LLMProvider):
	"""Adapter for OpenAI's Chat Completions API."""

	def __init__(
		self,
		*,
		api_key: str | None = None,
		base_url: str | None = None,
		default_model: str = "gpt-4o-mini",
		**_: Any,
	) -> None:
		self.api_key = api_key
		self.base_url = base_url
		self.default_model = default_model
		self._client: Any = None  # lazy
		self._tiktoken = None  # lazy

	# ---- chat --------------------------------------------------------------

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
			# Streaming is intentionally out of scope for Phase 16 —
			# the facade exposes a hook but the base path stays sync.
			logger.debug("stream=True requested but sync path used for Phase 16")

		client = self._get_client()
		payload: dict[str, Any] = {
			"model": model or self.default_model,
			"messages": messages,
			"temperature": temperature,
			"max_tokens": max_tokens,
		}
		if tools:
			payload["tools"] = tools
			payload["tool_choice"] = tool_choice
		if response_format:
			payload["response_format"] = response_format
		payload.update(extra)

		raw = client.chat.completions.create(**payload)
		return self._normalise(raw, payload["model"])

	def stream_complete(
		self,
		messages: list[dict],
		*,
		tools: list[dict] | None = None,
		tool_choice: str | dict = "auto",
		response_format: dict | None = None,
		temperature: float = 0.0,
		max_tokens: int = 4_096,
		model: str | None = None,
		**extra: Any,
	) -> Iterator[StreamDelta]:
		"""Token-by-token streaming for OpenAI chat completions.

		Sets ``stream=True`` + ``stream_options={"include_usage": True}``
		so the terminal chunk carries final ``usage`` numbers — without
		this OpenAI omits usage on streamed responses.
		"""

		client = self._get_client()
		payload: dict[str, Any] = {
			"model": model or self.default_model,
			"messages": messages,
			"temperature": temperature,
			"max_tokens": max_tokens,
			"stream": True,
			"stream_options": {"include_usage": True},
		}
		if tools:
			payload["tools"] = tools
			payload["tool_choice"] = tool_choice
		if response_format:
			payload["response_format"] = response_format
		payload.update(extra)

		text_parts: list[str] = []
		# OpenAI streams tool_call deltas keyed by index; arguments arrive
		# as fragmentary JSON strings we concatenate per index.
		tool_buffers: dict[int, dict[str, Any]] = {}
		finish_reason = "stop"
		usage_in = 0
		usage_out = 0
		usage_total = 0
		target = payload["model"]

		try:
			stream = client.chat.completions.create(**payload)
			for chunk in stream:
				try:
					data = chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
				except Exception:
					continue
				usage = data.get("usage") or {}
				if usage:
					usage_in = int(usage.get("prompt_tokens") or usage_in)
					usage_out = int(usage.get("completion_tokens") or usage_out)
					usage_total = int(usage.get("total_tokens") or usage_total)
				choices = data.get("choices") or []
				if not choices:
					continue
				choice = choices[0]
				delta = choice.get("delta") or {}
				fr = choice.get("finish_reason")
				if fr:
					finish_reason = fr
				content_delta = delta.get("content")
				if content_delta:
					text_parts.append(content_delta)
					yield StreamDelta(kind="text", text=content_delta)
				for tc in delta.get("tool_calls") or []:
					idx = int(tc.get("index", 0) or 0)
					buf = tool_buffers.setdefault(
						idx, {"id": "", "name": "", "args": ""}
					)
					if tc.get("id"):
						# First fragment carries id + name; emit a start.
						if not buf["id"]:
							buf["id"] = tc.get("id") or ""
							fn = tc.get("function") or {}
							buf["name"] = fn.get("name") or buf["name"]
							yield StreamDelta(
								kind="tool_use_start",
								tool_call_index=idx,
								tool_call_id=buf["id"],
								tool_name=buf["name"],
							)
						else:
							buf["id"] = tc.get("id") or buf["id"]
					fn = tc.get("function") or {}
					if fn.get("name") and not buf["name"]:
						buf["name"] = fn["name"]
					args_chunk = fn.get("arguments")
					if args_chunk:
						buf["args"] += args_chunk
						yield StreamDelta(
							kind="tool_use_delta",
							tool_call_index=idx,
							tool_arguments_delta=args_chunk,
						)
		except Exception as exc:  # noqa: BLE001
			logger.warning(f"openai stream aborted: {exc}")
			yield StreamDelta(kind="error", error=str(exc))
			return

		import json as _json

		tool_calls: list[ToolCall] = []
		for idx in sorted(tool_buffers.keys()):
			buf = tool_buffers[idx]
			raw_args = buf.get("args") or ""
			try:
				args = _json.loads(raw_args) if raw_args.strip() else {}
			except ValueError:
				args = {"_raw": raw_args}
			tool_calls.append(
				ToolCall(name=buf["name"], arguments=args, call_id=buf["id"])
			)
			yield StreamDelta(
				kind="tool_use_stop",
				tool_call_index=idx,
				tool_call_id=buf["id"],
				tool_name=buf["name"],
			)

		response = LLMResponse(
			content="".join(text_parts) or None,
			tool_calls=tool_calls,
			finish_reason=finish_reason,
			usage=TokenUsage(prompt=usage_in, completion=usage_out, total=usage_total),
			raw={"_idp_streamed": True},
			model=target,
			provider="openai",
		)
		yield StreamDelta(kind="final", response=response)

	def count_tokens(self, messages: list[dict], *, model: str | None = None) -> int:
		target = model or self.default_model
		tk = self._get_tiktoken()
		if tk is None:
			# char/4 heuristic on concatenated content
			text = "\n".join(str(m.get("content", "")) for m in messages)
			return max(1, len(text) // 4)
		try:
			enc = tk.encoding_for_model(target)
		except Exception:
			enc = tk.get_encoding("cl100k_base")
		total = 0
		for m in messages:
			total += len(enc.encode(str(m.get("content", ""))))
		return total

	# ---- helpers ------------------------------------------------------------

	def _get_client(self) -> Any:
		if self._client is not None:
			return self._client
		try:
			from openai import OpenAI
		except ImportError as exc:
			raise LLMProviderUnavailableError(
				"openai SDK not installed; run `pip install openai` or install the `llm-openai` extra"
			) from exc
		kwargs: dict[str, Any] = {}
		if self.api_key:
			kwargs["api_key"] = self.api_key
		if self.base_url:
			kwargs["base_url"] = self.base_url
		self._client = OpenAI(**kwargs)
		return self._client

	def _get_tiktoken(self):
		if self._tiktoken is not None:
			return self._tiktoken
		try:
			import tiktoken  # type: ignore[import-untyped]
		except ImportError:
			return None
		self._tiktoken = tiktoken
		return tiktoken

	def _normalise(self, raw: Any, model: str) -> LLMResponse:
		"""Translate an OpenAI SDK response into :class:`LLMResponse`."""

		try:
			# SDK returns pydantic objects; fall back to dict access.
			data = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
		except Exception as exc:
			raise LLMResponseParseError(f"cannot decode OpenAI response: {exc}") from exc

		choices = data.get("choices") or []
		if not choices:
			raise LLMResponseParseError("OpenAI response has no choices")
		choice = choices[0]
		msg = choice.get("message") or {}

		tool_calls: list[ToolCall] = []
		for tc in msg.get("tool_calls") or []:
			fn = tc.get("function") or {}
			import json as _json

			args_raw = fn.get("arguments")
			try:
				args = _json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
			except ValueError:
				args = {"_raw": args_raw}
			tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args, call_id=tc.get("id")))

		usage = data.get("usage") or {}
		return LLMResponse(
			content=msg.get("content"),
			tool_calls=tool_calls,
			finish_reason=choice.get("finish_reason", "stop"),
			usage=TokenUsage(
				prompt=int(usage.get("prompt_tokens") or 0),
				completion=int(usage.get("completion_tokens") or 0),
				total=int(usage.get("total_tokens") or 0),
			),
			raw=data,
			model=model,
			provider="openai",
		)
