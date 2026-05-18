# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""LLMClient facade.

Wraps a concrete :class:`LLMProvider` with cross-cutting concerns:

* Retries with exponential backoff for transient errors.
* Pre-flight budget enforcement via :func:`enforce_budget`.
* Cost accounting via :func:`estimate_cost`.
* A capability-query helper used by the hybrid mapper.
* Two-tier model routing (§TE.3): callers pass a ``purpose`` (e.g.
  ``classification`` / ``extraction``) and the client resolves the
  matching row in ``IDP Settings.llm_model_routes`` to pick a cheap or
  expensive model+provider.  Falls back to the default provider/model
  when no route matches.

A single API key is decrypted once from IDP Settings; secondary
providers selected via routes share the same key when they're the
same vendor.  Ollama is keyless.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from idp.core.exceptions import (
	LLMBudgetExceededError,
	LLMError,
	LLMProviderUnavailableError,
)
from idp.core.logger import get_logger
from idp.llm.model_registry import get_model_info
from idp.llm.providers.base import LLMProvider, LLMResponse, StreamDelta
from idp.llm.providers.registry import get_provider
from idp.llm.token_counter import enforce_budget, estimate_cost

logger = get_logger("idp.llm.client")

DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 0.5  # seconds
# Default cap on output tokens per response.  Overridden by
# ``IDP Settings.llm_max_tokens`` when the client is built via
# :meth:`LLMClient.from_settings`.  Sized large enough that
# multi-page invoice confirmation payloads (header + items + taxes)
# don't get truncated mid-JSON on Anthropic / OpenAI models.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384


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
		routes: list[dict] | None = None,
		provider_kwargs: dict[str, Any] | None = None,
		default_max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
	) -> None:
		self.provider = provider
		self.default_model = default_model
		self.max_retries = max_retries
		self.backoff_base = backoff_base
		self.on_budget_check = on_budget_check or enforce_budget
		# Routes are normalised dicts: {"purpose","provider","model","tier"}.
		self.routes: list[dict] = list(routes or [])
		# Cap on output tokens applied to every ``chat()`` call unless the
		# caller passes an explicit ``max_tokens`` argument.  Sourced from
		# ``IDP Settings.llm_max_tokens`` when built via from_settings().
		self.default_max_tokens = int(default_max_tokens) if default_max_tokens else DEFAULT_MAX_OUTPUT_TOKENS
		# Init kwargs (api_key, host_url, etc.) reused when we have to
		# instantiate a secondary provider on demand.
		self._provider_kwargs: dict[str, Any] = dict(provider_kwargs or {})
		# Cache of (provider_name -> LLMProvider) for routed lookups.
		default_name = getattr(provider, "name", "") or provider.__class__.__name__.lower()
		self._provider_cache: dict[str, LLMProvider] = {default_name: provider}

	# ---- factory ------------------------------------------------------------

	@classmethod
	def from_settings(cls) -> "LLMClient":
		"""Build an :class:`LLMClient` from the active site's IDP Settings.

		Reads the single ``llm_api_key`` field and the active ``llm_provider``
		so swapping providers is a one-line settings change with no key
		management churn.  Ollama ignores the key.  Two-tier routes
		(``llm_model_routes`` child table) are loaded for §TE.3 routing.
		"""

		try:
			import frappe
		except ImportError as exc:
			raise LLMProviderUnavailableError("frappe is not available") from exc

		try:
			doc = frappe.get_single("IDP Settings")
		except Exception as exc:
			raise LLMProviderUnavailableError(f"cannot load IDP Settings: {exc}") from exc

		if not getattr(doc, "enable_hybrid_mapper", 0) and not getattr(doc, "llm_enabled", 0):
			raise LLMProviderUnavailableError("LLM is disabled in IDP Settings")

		provider_name = (getattr(doc, "llm_provider", None) or "openai").strip()
		model = (getattr(doc, "llm_model", None) or "").strip()
		if not model:
			# Sensible default per provider so admins don't *have* to set both.
			# Anthropic default aligned with Phase 16 spec (Opus 4.5).
			model = {
				"openai": "gpt-4o-mini",
				"anthropic": "claude-opus-4-5-20251101",
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

		routes = _normalise_routes(getattr(doc, "llm_model_routes", None) or [])
		# Keep api_key/host on hand for secondary providers selected
		# via routes (same vendor reuses the same key).
		provider_kwargs: dict[str, Any] = {}
		if api_key:
			provider_kwargs["api_key"] = api_key
		host = (getattr(doc, "ollama_host_url", None) or "").strip()
		if host:
			provider_kwargs["host_url"] = host

		# Output-token cap is driven by IDP Settings so admins can
		# raise it for multi-page invoices without code changes.
		try:
			configured_max_tokens = int(getattr(doc, "llm_max_tokens", 0) or 0)
		except (TypeError, ValueError):
			configured_max_tokens = 0
		default_max_tokens = configured_max_tokens or DEFAULT_MAX_OUTPUT_TOKENS

		return cls(
			provider,
			default_model=model or provider.default_model,
			routes=routes,
			provider_kwargs=provider_kwargs,
			default_max_tokens=default_max_tokens,
		)

	# ---- routing ------------------------------------------------------------

	def resolve_route(self, purpose: str | None) -> tuple[LLMProvider, str]:
		"""Return ``(provider, model)`` for *purpose*.

		Looks up the first matching row in ``llm_model_routes``.  Falls
		back to the default provider/model when *purpose* is None or no
		route matches — this preserves the v1 single-provider deployment
		model.
		"""

		if not purpose or not self.routes:
			return self.provider, self.default_model
		for row in self.routes:
			if row.get("purpose") == purpose:
				provider_name = (row.get("provider") or "").strip()
				model_name = (row.get("model") or "").strip()
				if not provider_name or not model_name:
					return self.provider, self.default_model
				return self._get_or_build_provider(provider_name, model_name), model_name
		return self.provider, self.default_model

	def _get_or_build_provider(self, name: str, model: str) -> LLMProvider:
		cached = self._provider_cache.get(name)
		if cached is not None:
			return cached
		kwargs = dict(self._provider_kwargs)
		kwargs["default_model"] = model
		# Ollama doesn't take an api_key.
		if name == "ollama":
			kwargs.pop("api_key", None)
		provider = get_provider(name, **kwargs)
		self._provider_cache[name] = provider
		return provider

	# ---- chat ---------------------------------------------------------------

	def chat(
		self,
		messages: list[dict],
		*,
		tools: list[dict] | None = None,
		tool_choice: str | dict = "auto",
		response_format: dict | None = None,
		temperature: float = 0.0,
		max_tokens: int | None = None,
		model: str | None = None,
		user: str | None = None,
		purpose: str | None = None,
		**extra: Any,
	) -> LLMResponse:
		"""Run a chat completion with retries and budget enforcement.

		If *model* is omitted and *purpose* is supplied, the route table
		is consulted to pick the cheap or expensive tier.  Pre-flight
		budget check uses the provider's tokeniser so we don't burn quota
		on a request that cannot fit.  Final cost is attached to
		``response.raw['_idp_cost_usd']``.

		``max_tokens`` falls back to :attr:`default_max_tokens` (sourced
		from IDP Settings.llm_max_tokens) so admins can raise the output
		budget for long confirmation payloads without code changes.
		"""

		if max_tokens is None or max_tokens <= 0:
			max_tokens = self.default_max_tokens

		if model:
			provider = self.provider
			target = model
		else:
			provider, target = self.resolve_route(purpose)

		estimated = provider.count_tokens(messages, model=target)

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
			provider,
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
		if purpose:
			response.raw.setdefault("_idp_purpose", purpose)
		return response

	def stream_chat(
		self,
		messages: list[dict],
		*,
		tools: list[dict] | None = None,
		tool_choice: str | dict = "auto",
		response_format: dict | None = None,
		temperature: float = 0.0,
		max_tokens: int | None = None,
		model: str | None = None,
		user: str | None = None,
		purpose: str | None = None,
		**extra: Any,
	) -> Iterator[StreamDelta]:
		"""Phase 30 — stream :class:`StreamDelta` deltas from the provider.

		Mirrors :meth:`chat`'s pre-flight checks (budget + route
		resolution).  Retries are not applied to streams — a transient
		failure mid-stream yields a ``StreamDelta(kind="error", ...)``
		instead, which the agent loop persists with ``status=cancelled``.

		Cost accounting happens after the final delta is yielded so the
		``response.raw['_idp_cost_usd']`` field is consistent with the
		non-streaming path.
		"""

		if max_tokens is None or max_tokens <= 0:
			max_tokens = self.default_max_tokens

		if model:
			provider = self.provider
			target = model
		else:
			provider, target = self.resolve_route(purpose)

		estimated = provider.count_tokens(messages, model=target)
		if user:
			try:
				self.on_budget_check(user, estimated + max_tokens)
			except LLMBudgetExceededError:
				raise
			except Exception as exc:
				logger.debug(f"budget enforcement skipped: {exc}")

		for delta in provider.stream_complete(
			messages,
			tools=tools,
			tool_choice=tool_choice,
			response_format=response_format,
			temperature=temperature,
			max_tokens=max_tokens,
			model=target,
			**extra,
		):
			if delta.kind == "final" and delta.response is not None:
				delta.response.raw.setdefault(
					"_idp_cost_usd", estimate_cost(delta.response.usage, target)
				)
				if purpose:
					delta.response.raw.setdefault("_idp_purpose", purpose)
			yield delta

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

	def _chat_with_retry(
		self,
		provider: LLMProvider,
		messages: list[dict],
		**kwargs: Any,
	) -> LLMResponse:
		last_exc: Exception | None = None
		for attempt in range(self.max_retries + 1):
			try:
				return provider.chat(messages, **kwargs)
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


def _normalise_routes(rows: Any) -> list[dict]:
	"""Convert a Frappe child-table iterable into a list of plain dicts.

	The IDP LLM Model Route schema is ``purpose`` / ``provider`` /
	``model_name`` / ``tier``.  We surface ``model`` (not ``model_name``)
	in the normalised dict for symmetry with ``LLMClient.chat(model=...)``.
	"""

	out: list[dict] = []
	for row in rows or []:
		# Each row may be a Frappe Document or a plain dict (in tests).
		def _get(field: str) -> str:
			val = row.get(field) if isinstance(row, dict) else getattr(row, field, None)
			return val.strip() if isinstance(val, str) else ""

		purpose = _get("purpose")
		provider = _get("provider")
		model = _get("model_name") or _get("model")
		tier = _get("tier") or "expensive"
		if not purpose or not provider or not model:
			# Skip incomplete rows quietly — Settings validation already
			# enforces purpose uniqueness; partial rows are best ignored.
			continue
		out.append({"purpose": purpose, "provider": provider, "model": model, "tier": tier})
	return out


__all__ = ["LLMClient"]
