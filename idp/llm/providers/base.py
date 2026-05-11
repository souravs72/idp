# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""LLM provider base types.

Defines the vendor-agnostic :class:`LLMProvider` ABC plus the small
dataclasses every provider emits or consumes.  Capabilities (vision /
tools / JSON mode / pricing / context window) live in
:mod:`idp.llm.model_registry` and are looked up per-model rather
than per-provider — a single provider (e.g. OpenAI) can serve models
with very different feature matrices.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class TokenUsage:
	"""Prompt / completion / total token counts reported by a provider."""

	prompt: int = 0
	completion: int = 0
	total: int = 0

	def __post_init__(self) -> None:
		# Providers sometimes omit "total"; synthesize it for consistency.
		if not self.total and (self.prompt or self.completion):
			self.total = self.prompt + self.completion


@dataclass
class ToolCall:
	"""A structured tool invocation decoded from the provider's response."""

	name: str
	arguments: dict = field(default_factory=dict)
	call_id: str | None = None


@dataclass
class LLMResponse:
	"""Normalised response returned from every provider's ``chat()`` call."""

	content: str | None
	tool_calls: list[ToolCall] = field(default_factory=list)
	finish_reason: str = "stop"
	usage: TokenUsage = field(default_factory=TokenUsage)
	raw: dict = field(default_factory=dict)
	model: str = ""
	provider: str = ""


@dataclass
class ModelCapabilities:
	"""Per-model feature + pricing metadata.

	Populated from :mod:`idp.llm.model_registry`, which ships baseline
	entries and merges admin overrides from ``IDP Settings.model_overrides``.
	"""

	context_window: int = 8_192
	supports_vision: bool = False
	supports_tools: bool = True
	supports_json_mode: bool = True
	input_cost_per_1k: float = 0.0  # USD per 1k input tokens
	output_cost_per_1k: float = 0.0  # USD per 1k output tokens


class LLMProvider(ABC):
	"""Vendor-agnostic chat-completion interface.

	Concrete adapters register themselves via
	:func:`idp.llm.providers.registry.register_provider`.  The
	``name`` class attribute is set by the decorator.
	"""

	name: ClassVar[str] = ""

	@abstractmethod
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
		"""Perform a synchronous chat completion.

		``messages`` follows the OpenAI schema — ``[{"role": ..., "content": ...}]`` —
		and providers are responsible for translating as needed.
		"""

	@abstractmethod
	def count_tokens(self, messages: list[dict], *, model: str | None = None) -> int:
		"""Return an estimated prompt-token count for ``messages``.

		Providers should use the SDK's official tokeniser where available
		and fall back to a ``len(text) / 4`` heuristic otherwise.
		"""

	def capabilities(self, model: str) -> ModelCapabilities:
		"""Return :class:`ModelCapabilities` for *model*.

		The default implementation delegates to the global model registry
		so adapters only override when they need provider-specific tweaks.
		"""

		# Imported lazily to avoid a registry ↔ base circular import.
		from idp.llm.model_registry import get_model_info

		info = get_model_info(model)
		return ModelCapabilities(
			context_window=info.context_window,
			supports_vision=info.supports_vision,
			supports_tools=info.supports_tools,
			supports_json_mode=info.supports_json_mode,
			input_cost_per_1k=info.input_cost_per_1k,
			output_cost_per_1k=info.output_cost_per_1k,
		)
