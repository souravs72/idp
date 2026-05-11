# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Ollama (local LLM server) adapter.

Talks to a local Ollama instance over HTTP using the chat completions
endpoint.  ``httpx`` is the only dependency and ships with Frappe.
Most local models do not yet support tool calling or vision; capabilities
are looked up per-model via the model registry rather than assumed.
"""

from __future__ import annotations

from typing import Any

from idp.core.exceptions import LLMProviderUnavailableError, LLMResponseParseError
from idp.core.logger import get_logger
from idp.idp.llm.providers.base import LLMProvider, LLMResponse, TokenUsage, ToolCall
from idp.idp.llm.providers.registry import register_provider

logger = get_logger("idp.llm.ollama")

DEFAULT_HOST = "http://localhost:11434"


@register_provider("ollama")
class OllamaProvider(LLMProvider):
	"""Adapter for the local Ollama HTTP API."""

	def __init__(
		self,
		*,
		host_url: str = DEFAULT_HOST,
		default_model: str = "llama3.1:8b",
		timeout: float = 120.0,
		**_: Any,
	) -> None:
		self.host_url = host_url.rstrip("/")
		self.default_model = default_model
		self.timeout = timeout

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
		try:
			import httpx
		except ImportError as exc:  # pragma: no cover — httpx ships with Frappe
			raise LLMProviderUnavailableError("httpx is required for the Ollama provider") from exc

		target = model or self.default_model
		payload: dict[str, Any] = {
			"model": target,
			"messages": messages,
			"stream": False,
			"options": {
				"temperature": temperature,
				"num_predict": max_tokens,
			},
		}
		if tools:
			payload["tools"] = tools  # newer Ollama builds accept OpenAI-style tools
		if response_format and response_format.get("type") == "json_object":
			payload["format"] = "json"
		payload.update(extra)

		try:
			resp = httpx.post(
				f"{self.host_url}/api/chat",
				json=payload,
				timeout=self.timeout,
			)
			resp.raise_for_status()
			data = resp.json()
		except httpx.HTTPError as exc:
			raise LLMProviderUnavailableError(f"Ollama request failed at {self.host_url}: {exc}") from exc
		except ValueError as exc:
			raise LLMResponseParseError(f"Ollama returned non-JSON: {exc}") from exc

		return self._normalise(data, target)

	def count_tokens(self, messages: list[dict], *, model: str | None = None) -> int:
		text = "\n".join(str(m.get("content", "")) for m in messages)
		return max(1, len(text) // 4)

	# ------------------------------------------------------------------
	# Phase 27 §27.2 — Vision OCR fallback
	# ------------------------------------------------------------------

	def vision_ocr(
		self,
		image_path: str,
		*,
		model: str | None = None,
		prompt: str | None = None,
		max_tokens: int = 4_096,
		timeout: float | None = None,
	) -> dict:
		"""OCR an image with a local LLaVA / minicpm-v vision model.

		Posts a base64-encoded image plus an OCR prompt to ``/api/chat``
		on the configured Ollama host and returns the recognised text.
		``confidence`` is synthesised because vision LLMs do not emit
		per-token scores; ``synthetic=True`` flags this for downstream
		consumers (e.g. the Phase 23 confidence chip).

		Returns a dict shaped:

		    {
		      "text": "...",
		      "confidence": 0.85,
		      "synthetic": True,
		      "model": "llava:13b",
		    }
		"""

		import base64

		try:
			import httpx
		except ImportError as exc:  # pragma: no cover — httpx ships with Frappe
			raise LLMProviderUnavailableError("httpx is required for the Ollama provider") from exc

		try:
			with open(image_path, "rb") as fh:
				image_b64 = base64.b64encode(fh.read()).decode("ascii")
		except OSError as exc:
			raise LLMProviderUnavailableError(
				f"Cannot read image for vision OCR: {exc}"
			) from exc

		target_model = model or "llava:13b"
		ocr_prompt = prompt or (
			"You are an OCR engine. Extract all visible text from the image "
			"verbatim, preserving line breaks. Do not add commentary, "
			"summarisation, or translation."
		)

		payload: dict[str, Any] = {
			"model": target_model,
			"messages": [
				{
					"role": "user",
					"content": ocr_prompt,
					"images": [image_b64],
				}
			],
			"stream": False,
			"options": {
				"temperature": 0.0,
				"num_predict": max_tokens,
			},
		}

		try:
			resp = httpx.post(
				f"{self.host_url}/api/chat",
				json=payload,
				timeout=timeout if timeout is not None else self.timeout,
			)
			resp.raise_for_status()
			data = resp.json()
		except httpx.HTTPError as exc:
			raise LLMProviderUnavailableError(
				f"Ollama vision request failed at {self.host_url}: {exc}"
			) from exc
		except ValueError as exc:
			raise LLMResponseParseError(f"Ollama returned non-JSON: {exc}") from exc

		message = data.get("message") or {}
		text = (message.get("content") or "").strip()
		return {
			"text": text,
			"confidence": 0.85,
			"synthetic": True,
			"model": target_model,
		}

	def _normalise(self, data: dict, model: str) -> LLMResponse:
		message = data.get("message") or {}
		content = message.get("content")

		tool_calls: list[ToolCall] = []
		for tc in message.get("tool_calls") or []:
			fn = tc.get("function") or {}
			args = fn.get("arguments")
			if isinstance(args, str):
				import json as _json

				try:
					args = _json.loads(args)
				except ValueError:
					args = {"_raw": args}
			tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args or {}))

		return LLMResponse(
			content=content,
			tool_calls=tool_calls,
			finish_reason="stop" if data.get("done") else "length",
			usage=TokenUsage(
				prompt=int(data.get("prompt_eval_count") or 0),
				completion=int(data.get("eval_count") or 0),
			),
			raw=data,
			model=model,
			provider="ollama",
		)
