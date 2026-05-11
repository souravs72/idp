# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""LLM provider abstraction, hybrid field mapping, and chatbot plumbing.

This package ships:

* A vendor-agnostic :class:`LLMProvider` ABC and a registry-based
  provider factory so new providers (Azure OpenAI, Bedrock, Mistral,
  vLLM, …) can be added without modifying core-app code (Phase 16).
* Built-in adapters for OpenAI, Anthropic, and Ollama (Phase 16).
* A :class:`LLMClient` facade with retries, budget enforcement and
  cost accounting (Phase 16).
* Tool/JSON schemas and prompt builders used by the hybrid mapper
  and the chatbot (Phase 16).
* :class:`FileAliasRegistry` and message rendering helpers that hide
  real ``file_url`` values from the LLM behind monotonic short
  aliases like ``file_1`` (Phase 18).

The hybrid field mapper lives in :mod:`idp.mappers.hybrid_mapper`.
"""

from idp.llm.file_alias import (
	AttachmentRecord,
	FileAliasRegistry,
	clear_request_cache,
	get_registry,
)
from idp.llm.message_renderer import (
	render_attachment_for_llm,
	render_history,
	render_user_message,
)
from idp.llm.providers.base import (
	LLMProvider,
	LLMResponse,
	ModelCapabilities,
	TokenUsage,
	ToolCall,
)
from idp.llm.providers.registry import (
	get_provider,
	list_registered_providers,
	register_provider,
)

__all__ = [
	"AttachmentRecord",
	"FileAliasRegistry",
	"LLMProvider",
	"LLMResponse",
	"ModelCapabilities",
	"TokenUsage",
	"ToolCall",
	"clear_request_cache",
	"get_provider",
	"get_registry",
	"list_registered_providers",
	"register_provider",
	"render_attachment_for_llm",
	"render_history",
	"render_user_message",
]
