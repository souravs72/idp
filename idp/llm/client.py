# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""LLMClient facade.

Wraps a concrete :class:`LLMProvider` with cross-cutting concerns:

* Retries with exponential backoff for transient errors.
* Pre-flight budget enforcement via :func:`enforce_budget`.
* Cost accounting via :func:`estimate_cost`.
* A capability-query helper used by the hybrid mapper.

Settings are deliberately simple: a single active provider plus a single
``llm_api_key`` field on IDP Settings (Ollama is keyless).  This matches
the "one provider at a time" deployment model.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from idp.core.exceptions import (
	LLMBudgetExceededError,
	LLMError,
	LLMProviderUnavailableError,
)
from idp.core.logger import get_logger
from idp.llm.model_registry import get_model_info
from idp.llm.providers.base import LLMProvider, LLMResponse
from idp.llm.providers.registry import get_provider
from idp.llm.token_counter import enforce_budget, estimate_cost

logger = get_logger("idp.llm.client")

DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 0.5  # seconds


class LLMClient:
	"""High-level facade used by hybrid mapper, chatbot and direct API."""

	def __init__(
		self,
		provider: LLMProvider,
		*,
		default_model: str,
		max_retries: int = DEFAULT_MAX_RETRIES,
		backoff_base: float = DEFAULT_BACKOFF_BASE,
		on_budget_check: Callable[[str, int], None] | None = None,
	) -> None:
		self.provider = provider
		self.default_model = default_model
		self.max_retries = max_retries
		self.backoff_base = backoff_base
		self.on_budget_check = on_budget_check or enforce_budget

	# ---- factory ------------------------------------------------------------

	@classmethod
	def from_settings(cls) -> "LLMClient":
		"""Build an :class:`LLMClient` from the active site's IDP Settings.

		Reads the single ``llm_api_key`` field and the active ``llm_provider``
		so swapping providers is a one-line settings change with no key
		management churn.  Ollama ignores the key.
		"""

		try:
			import frappe
		except ImportError as exc:
			raise LLMProviderUnavailableError("frappe is not available") from exc

		try:
			doc = frappe.get_single("IDP Settings")
		except Exception as exc:
			raise LLMProviderUnavailableError(f"cannot load IDP Settings: {exc}") from exc

		if not getattr(doc, "enable_hybrid_mapper", 0):
			raise LLMProviderUnavailableError("Hybrid mapper is disabled in IDP Settings")

		provider_name = (getattr(doc, "llm_provider", None) or "openai").strip()
		model = (getattr(doc, "llm_model", None) or "").strip()
		if not model:
			# Sensible default per provider so admins don't *have* to set both.
			model = {
				"openai": "gpt-4o-mini",
				"anthropic": "claude-haiku-4-5-20251001",
				"ollama": "llama3.1:8b",
			}.get(provider_name, "")

		# Decrypt the single API key once; Ollama ignores it.
		api_key = None
		if provider_name != "ollama":
			try:
				api_key = doc.get_password("llm_api_key", raise_exception=False)
			except Exception as exc:
				logger.debug(f"llm_api_key decrypt failed: {exc}")

		kwargs: dict[str, Any] = {"default_model": model} if model else {}
		if api_key:
			kwargs["api_key"] = api_key
		if provider_name == "ollama":
			host = (getattr(doc, "ollama_host_url", None) or "").strip()
			if host:
				kwargs["host_url"] = host

		provider = get_provider(provider_name, **kwargs)
		return cls(provider, default_model=model or provider.default_model)

	# ---- chat ---------------------------------------------------------------

	def chat(
		self,
		messages: list[dict],
		*,
		tools: list[dict] | None = None,
		tool_choice: str | dict = "auto",
		response_format: dict | None = None,
		temperature: float = 0.0,
		max_tokens: int = 4_096,
		model: str | None = None,
		user: str | None = None,
		**extra: Any,
	) -> LLMResponse:
		"""Run a chat completion with retries and budget enforcement.

		Pre-flight budget check uses the provider's tokeniser so we don't
		burn quota on a request that cannot fit.  Final accounting is
		attached to the response's ``raw['_idp_cost_usd']`` field.
		"""

		target = model or self.default_model
		estimated = self.provider.count_tokens(messages, model=target)

		if user:
			# Budget enforcement is best-effort; failures during the lookup
			# itself never block a request.
			try:
				self.on_budget_check(user, estimated + max_tokens)
			except LLMBudgetExceededError:
				raise
			except Exception as exc:
				logger.debug(f"budget enforcement skipped: {exc}")

		response = self._chat_with_retry(
			messages,
			tools=tools,
			tool_choice=tool_choice,
			response_format=response_format,
			temperature=temperature,
			max_tokens=max_tokens,
			model=target,
			**extra,
		)

		response.raw.setdefault("_idp_cost_usd", estimate_cost(response.usage, target))
		return response

	def supports(self, capability: str, *, model: str | None = None) -> bool:
		"""Quick capability lookup (``vision``, ``tools``, ``json_mode``)."""

		info = get_model_info(model or self.default_model)
		mapping = {
			"vision": info.supports_vision,
			"tools": info.supports_tools,
			"json_mode": info.supports_json_mode,
		}
		return bool(mapping.get(capability, False))

	# ---- internals ----------------------------------------------------------

	def _chat_with_retry(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
		last_exc: Exception | None = None
		for attempt in range(self.max_retries + 1):
			try:
				return self.provider.chat(messages, **kwargs)
			except LLMBudgetExceededError:
				raise
			except LLMError:
				# These are deterministic and won't be cured by retrying.
				raise
			except Exception as exc:
				last_exc = exc
				if attempt >= self.max_retries:
					break
				delay = self.backoff_base * (2**attempt)
				logger.warning(
					f"LLM call failed (attempt {attempt + 1}/{self.max_retries + 1}): {exc}; "
					f"retrying in {delay:.1f}s"
				)
				time.sleep(delay)
		# Wrap the final exception so callers see a uniform LLMError surface.
		raise LLMError(f"LLM call failed after {self.max_retries + 1} attempts: {last_exc}") from last_exc


__all__ = ["LLMClient"]
