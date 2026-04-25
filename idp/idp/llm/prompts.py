# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""System / user prompt builders for the hybrid mapper + chatbot.

The system prompt falls back through three layers:

1. :func:`idp.idp.advanced.prompt_library.load_prompt` — site-edited
   Phase-15 prompt gallery (industry-aware).
2. A shipped generic template when Phase 15 is absent or returns None.
3. A minimal hard-coded string when even the library import fails.
"""

from __future__ import annotations

import json
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.llm.prompts")

_GENERIC_SYSTEM_TEMPLATE = (
	"You are an intelligent document-processing assistant helping an "
	"ERPNext user map {doctype} documents. The user's preferred output "
	"language is {language}. "
	"Respond ONLY by calling the provided tool with the extracted field "
	"values. Do not invent values. Set confidence_scores[fieldname] to a "
	"number in [0, 1] for every mapped field. Leave fields you cannot "
	"determine out of the mapping rather than guessing."
)


def build_system_prompt(
	target_doctype: str,
	*,
	industry: str | None = None,
	output_language: str = "English",
) -> str:
	"""Return the system prompt for a mapping conversation.

	Tries the Phase 15 prompt gallery first (if available), then falls
	back to :data:`_GENERIC_SYSTEM_TEMPLATE`.
	"""

	try:
		from idp.idp.advanced.prompt_library import load_prompt

		prompt = load_prompt(target_doctype, industry=industry)
		if prompt:
			# Allow the shipped templates to use the same placeholders.
			return _safe_format(prompt, doctype=target_doctype, language=output_language)
	except Exception as exc:  # Phase 15 may be disabled, module missing, etc.
		logger.debug(f"prompt_library.load_prompt unavailable: {exc}")

	return _GENERIC_SYSTEM_TEMPLATE.format(doctype=target_doctype, language=output_language)


def build_user_message(
	extracted: dict,
	*,
	partial_mapping: dict | None = None,
	schema_hint: dict | None = None,
) -> str:
	"""Render the user-role message the LLM sees.

	Includes the raw extracted text/fields, the rule-based partial
	mapping (so the LLM can fill the gaps rather than starting from
	scratch), and an optional DocType schema hint.
	"""

	parts: list[str] = []
	parts.append("Here is the extracted content:")
	parts.append(_dump(extracted))

	if partial_mapping:
		parts.append("\nRule-based partial mapping (fill in or correct low-confidence values):")
		parts.append(_dump(partial_mapping))

	if schema_hint:
		parts.append("\nTarget DocType schema hint:")
		parts.append(_dump(schema_hint))

	parts.append(
		"\nCall map_document_fields with your best mapping. Include a confidence score for every field."
	)
	return "\n".join(parts)


def _dump(data: Any) -> str:
	try:
		return json.dumps(data, indent=2, ensure_ascii=False, default=str)
	except (TypeError, ValueError):
		return str(data)


def _safe_format(template: str, **kwargs: Any) -> str:
	"""``str.format`` that tolerates placeholders missing from *kwargs*."""

	try:
		return template.format(**kwargs)
	except (KeyError, IndexError):
		# Fallback: return the template unchanged so the site's prompt
		# is never clobbered by a missing variable.
		return template


__all__ = [
	"build_system_prompt",
	"build_user_message",
]
