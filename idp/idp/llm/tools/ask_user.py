# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``ask_user`` — pause the loop and surface a question to the human.

Ergonomically the LLM uses this when it can't disambiguate a value
without help (e.g., two suppliers with similar names).  The tool
returns ``stop_processing=True`` so the agent loop ends after writing
a QuestionCard to the conversation; the user's reply will arrive on
the next ``post_message`` round-trip.
"""

from __future__ import annotations

from idp.idp.llm.tools.base import ToolContext, ToolResult, tool

_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"question": {"type": "string", "description": "Question to show the user."},
		"fieldname": {
			"type": "string",
			"description": "Optional fieldname the question is about (for client-side highlighting).",
		},
		"candidates": {
			"type": "array",
			"description": "Optional list of candidate answers to render as quick-reply chips.",
			"items": {"type": "string"},
		},
	},
	"required": ["question"],
	"additionalProperties": False,
}


@tool(
	name="ask_user",
	description=(
		"Ask the user a clarifying question.  The agent loop ends after this "
		"call; the user's reply will arrive in the next message turn."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
)
def ask_user(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	question = (args.get("question") or "").strip()
	if not question:
		return ToolResult.fail(
			"question text is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	card_payload = {
		"card_type": "QuestionCard",
		"question": question,
		"fieldname": args.get("fieldname"),
		"candidates": args.get("candidates") or [],
	}

	return ToolResult(
		success=True,
		data={"awaiting_user_reply": True, "question": question},
		card=card_payload,
		# Halt this round of the agent loop — the user's reply re-enters
		# on the next post_message turn.
		stop_processing=True,
	)


__all__ = ["ask_user"]
