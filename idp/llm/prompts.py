# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""System / user prompt builders for the hybrid mapper + chatbot.

The system prompt falls back through three layers:

1. :func:`idp.advanced.prompt_library.load_prompt` — site-edited
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
		from idp.advanced.prompt_library import load_prompt

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


_CHAT_SYSTEM_TEMPLATE = (
	"You are an Intelligent Document Processing assistant for ERPNext.  Your "
	"job is to help the user extract structured data from uploaded documents "
	"and create or compare ERPNext records.\n"
	"\n"
	"Rules:\n"
	"1. Never guess a file URL or hash.  Always reference attached files by "
	"their file_id alias (e.g. file_1, file_2) as shown in attachment tags.\n"
	"2. Before creating any ERPNext document, you MUST call "
	"propose_create_document first to present the data to the user for "
	"review.  Only call create_document after the user confirms in the UI.\n"
	"3. propose_create_document and create_document are TERMINAL turns — "
	"the server renders a ConfirmationCard / InfoCard whose summary text "
	"is shown to the user as the assistant's reply.  Do NOT also write a "
	"prose paraphrase of the extracted data; just call the tool with a "
	"complete payload and let the card speak for itself.\n"
	"3a. compare_document renders a ComparisonCard in the UI that already "
	"displays the full field-by-field diff table.  After calling "
	"compare_document, do NOT reproduce the comparison data as a markdown "
	"table or list.  Instead write only your observations, interpretation "
	"of the differences, and suggested next steps in plain prose.\n"
	"4. If a tool returns stop_processing=true, stop immediately and explain "
	"the error to the user.  Do not retry.\n"
	"5. Prefer the rule-based mapper output already present in tool results.  "
	"Only propose corrections where the rule mapper confidence is low or "
	"required fields are missing.\n"
	"6. NEVER call resolve_masters(mode='create') autonomously. When masters "
	"(Supplier, Customer, Item, UOM, Account) are missing or extracted items/taxes "
	"have status=\"New\", surface them via propose_create_document — the "
	"ConfirmationCard will let the user review and approve creation. "
	"Only call resolve_masters(mode='report') when you need to inspect what is "
	"missing before proposing the document.\n"
	"7. When unsure about a value, prefer ask_user over guessing.\n"
	"8. Output all user-facing text in {language}.\n"
	"9. For transactional DocTypes that have child tables (Purchase Invoice / "
	"Sales Invoice / Purchase Order / Sales Order / Delivery Note / Purchase "
	"Receipt / Quotation / Journal Entry, etc.), you MUST populate the line-item "
	"and tax arrays on propose_create_document — never submit a header-only "
	"payload.  If extract_document returned tables=[] but the OCR text clearly "
	"contains a line-item table (description / qty / rate / amount columns) or "
	"a tax breakdown (CGST / SGST / IGST / VAT / GST rows), parse the rows from "
	"the text yourself and emit them under `items` and `taxes`.  When a document "
	"spans multiple pages, call extract_document with offset=<next_offset> to page "
	"through the full text and aggregate items from every page before proposing.  "
	"If after a genuine attempt no items can be located, call ask_user rather than "
	"silently proposing an empty items array.\n"
	"\n"
	"Target DocType: {doctype}\n"
	"Current company: {company}"
)


def build_chat_system_prompt(
	*,
	target_doctype: str | None = None,
	company: str | None = None,
	output_language: str = "English",
) -> str:
	"""Return the system prompt for the Phase 19 agent loop.

	Lays out the tool-calling rules, the alias contract, and the
	stop-on-error semantics in a form every provider tolerates.

	Phase 26 §26.4: if an ``IDP Prompt Template`` matches the
	conversation's ``(target_doctype, output_language)`` it supersedes
	the hard-coded template.  Skills (§26.6) are concatenated after.
	"""

	doctype = target_doctype or "(any supported DocType)"
	company_str = company or "(none — ask the user if needed)"
	ctx = {
		"doctype": doctype,
		"target_doctype": doctype,
		"company": company_str,
		"language": output_language,
		"output_language": output_language,
	}

	prompt: str | None = None
	try:
		from idp.llm.prompt_templates import render_match

		prompt = render_match(
			target_doctype=target_doctype,
			language=output_language,
			context=ctx,
		)
	except Exception:
		logger.exception("prompt_templates.render_match failed — using default")

	if not prompt:
		prompt = _CHAT_SYSTEM_TEMPLATE.format(
			doctype=doctype, company=company_str, language=output_language
		)

	# Append matching skills (§26.6) — best-effort, never raise.
	try:
		from idp.llm.skills import get_skills_block

		extra = get_skills_block(target_doctype=target_doctype, language=output_language)
		if extra:
			prompt = f"{prompt}\n\n{extra}"
	except Exception:
		logger.exception("skills.get_skills_block failed — skipping")

	return prompt


__all__ = [
	"build_chat_system_prompt",
	"build_system_prompt",
	"build_user_message",
]
