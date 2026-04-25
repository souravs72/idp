# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""LLM provider abstraction + hybrid field mapping (Phase 16).

This package ships:

* A vendor-agnostic :class:`LLMProvider` ABC and a registry-based
  provider factory so new providers (Azure OpenAI, Bedrock, Mistral,
  vLLM, …) can be added without modifying core-app code.
* Built-in adapters for OpenAI, Anthropic, and Ollama.
* A :class:`LLMClient` facade with retries, budget enforcement and
  cost accounting.
* Tool/JSON schemas and prompt builders used by the hybrid mapper
  and the upcoming chatbot (Phase 18).

The hybrid field mapper lives in :mod:`idp.idp.mappers.hybrid_mapper`.
"""

from idp.idp.llm.providers.base import (
	LLMProvider,
	LLMResponse,
	ModelCapabilities,
	TokenUsage,
	ToolCall,
)
from idp.idp.llm.providers.registry import (
	get_provider,
	list_registered_providers,
	register_provider,
)

__all__ = [
	"LLMProvider",
	"LLMResponse",
	"ModelCapabilities",
	"TokenUsage",
	"ToolCall",
	"get_provider",
	"list_registered_providers",
	"register_provider",
]
