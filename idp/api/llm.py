# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 16 public API — LLM access + hybrid field mapping.

All endpoints require an authenticated user.  ``hybrid_map`` runs as
the calling user, while diagnostic / settings endpoints are restricted
to System Manager via :func:`frappe.only_for`.
"""

from __future__ import annotations

from typing import Any

import frappe

from idp.core.exceptions import LLMError
from idp.core.logger import get_logger

logger = get_logger("idp.api.llm")


@frappe.whitelist()
def list_providers() -> dict:
	"""Return the registered LLM providers + known model metadata.

	Useful for the settings UI's provider/model picker.  Auto-loads any
	site-declared custom providers as a side effect.
	"""

	from idp.idp.llm.model_registry import as_dict, list_known_models
	from idp.idp.llm.providers.registry import list_registered_providers

	return {
		"providers": list_registered_providers(),
		"models": [as_dict(m) for m in list_known_models()],
	}


@frappe.whitelist()
def estimate_chat_cost(model: str, prompt_tokens: int, completion_tokens: int) -> dict:
	"""Estimate USD cost for a hypothetical chat completion."""

	from idp.idp.llm.providers.base import TokenUsage
	from idp.idp.llm.token_counter import estimate_cost

	usage = TokenUsage(prompt=int(prompt_tokens), completion=int(completion_tokens))
	return {
		"model": model,
		"prompt_tokens": usage.prompt,
		"completion_tokens": usage.completion,
		"total_tokens": usage.total,
		"estimated_cost_usd": estimate_cost(usage, model),
	}


@frappe.whitelist()
def chat(messages: list | str, model: str | None = None, **extra: Any) -> dict:
	"""Thin pass-through to :meth:`LLMClient.chat`.

	System Manager only — this is a debugging surface, not an end-user
	feature; the Phase 18 chatbot will expose a user-facing wrapper.
	"""

	frappe.only_for("System Manager")

	from idp.idp.llm.client import LLMClient

	if isinstance(messages, str):
		import json as _json

		messages = _json.loads(messages)
	if not isinstance(messages, list):
		frappe.throw("messages must be a JSON list of {role, content} objects")

	client = LLMClient.from_settings()
	response = client.chat(messages, model=model, user=frappe.session.user, **extra)

	return {
		"content": response.content,
		"tool_calls": [
			{"name": tc.name, "arguments": tc.arguments, "id": tc.call_id} for tc in response.tool_calls
		],
		"finish_reason": response.finish_reason,
		"usage": {
			"prompt": response.usage.prompt,
			"completion": response.usage.completion,
			"total": response.usage.total,
		},
		"model": response.model,
		"provider": response.provider,
		"cost_usd": response.raw.get("_idp_cost_usd"),
	}


@frappe.whitelist()
def hybrid_map(file_url: str, target_doctype: str, company: str | None = None) -> dict:
	"""Run hybrid (rule + LLM) mapping for an uploaded file.

	Returns a serialisable view of :class:`MappedDocument` with provenance
	in ``confidence_scores`` so the UI can show which fields the LLM
	contributed.
	"""

	from idp.idp.extractors import extract_from_file
	from idp.idp.llm.client import LLMClient
	from idp.idp.mappers import FieldMapper
	from idp.idp.mappers.hybrid_mapper import HybridFieldMapper

	if not file_url:
		frappe.throw("file_url is required")
	if not target_doctype:
		frappe.throw("target_doctype is required")

	extracted = extract_from_file(file_url)

	try:
		llm_client = LLMClient.from_settings()
	except LLMError as exc:
		# Hybrid mapper disabled or LLM unavailable — fall back to rule-only
		# rather than failing the request.
		logger.info(f"hybrid_map falling back to rule-only mapping: {exc}")
		mapped = FieldMapper().map_fields(extracted, target_doctype, company=company)
		mapped.warnings.append(f"hybrid: llm unavailable ({exc}); rule-only mapping returned")
	else:
		mapper = HybridFieldMapper(FieldMapper(), llm_client)
		mapped = mapper.map_fields(
			extracted,
			target_doctype,
			company=company,
			user=frappe.session.user,
		)

	return {
		"doctype": mapped.doctype,
		"header": mapped.header,
		"items": mapped.items,
		"unmapped_fields": mapped.unmapped_fields,
		"confidence_scores": mapped.confidence_scores,
		"warnings": mapped.warnings,
		"link_resolutions": mapped.link_resolutions,
	}
