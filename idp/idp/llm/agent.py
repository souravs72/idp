# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDPAgent — orchestrates the LLM tool-calling loop (Phase 19).

The agent stitches Phase 16 (LLM client + provider abstraction),
Phase 17 (Conversation/Message DocTypes), Phase 18 (file alias
registry + message renderer), and Phase 19 (tool registry) into one
control loop.

Lifecycle of a single ``run()`` invocation:

1. Persist the user's new message (unless an empty re-trigger run).
2. Build the LLM context: system prompt + rendered history + tool schemas.
3. Call ``provider.chat()``.
4. Persist the assistant message (and any tool calls).
5. For each tool call: dispatch, persist a tool-role message with
   the result.  If ``stop_processing=True`` — break.
6. If the assistant produced no tool calls — break.
7. Repeat up to ``max_iterations``.

Realtime events are published at each step so the chatbot UI can
render progress without waiting for the loop to finish.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.llm.agent")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AgentRunResult:
	"""Summary of a single ``IDPAgent.run`` invocation."""

	conversation_id: str
	new_messages: list[dict]
	iterations: int
	stop_reason: str
	# Aggregated cost & token totals across this run.
	tokens_in: int = 0
	tokens_out: int = 0
	cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class IDPAgent:
	"""Run one round of the LLM tool-calling loop on a conversation."""

	#: Hard upper bound on iterations to prevent runaway loops.
	max_iterations: int = 12

	#: Names from the registry that should NOT be exposed to the LLM.
	#: ``create_document`` is omitted here because it requires the
	#: ``user_confirmed`` flag, which the API endpoint sets explicitly
	#: after the user clicks "Submit" on the ConfirmationCard.
	#: We still allow the LLM to *reference* it via propose_create_document.
	hidden_tools: tuple[str, ...] = ()

	def __init__(
		self,
		conversation_id: str,
		*,
		client: Any | None = None,
		max_iterations: int | None = None,
	) -> None:
		self.conversation_id = conversation_id
		self._client = client
		if max_iterations is not None:
			self.max_iterations = int(max_iterations)

	# ------------------------------------------------------------------ entry

	def run(
		self,
		*,
		user_message: str | None = None,
		attachments: list[dict] | None = None,
		user_confirmed_action: dict | None = None,
	) -> AgentRunResult:
		"""Run one round.

		Parameters
		----------
		user_message
		    Free-form text from the user.  Empty string permitted when
		    *user_confirmed_action* is provided (re-trigger after
		    ConfirmationCard click).
		attachments
		    List of ``{file_url, file_name, mime_type, file_size?,
		    tabfile_name?}`` dicts uploaded with this turn.
		user_confirmed_action
		    Optional dict signalling the user accepted a previously
		    proposed action.  When set, the agent injects a synthetic
		    ``tool`` role message with ``user_confirmed=True`` so the
		    next ``chat()`` call can immediately invoke ``create_document``.
		"""

		import frappe

		from idp.idp.llm.client import LLMClient
		from idp.idp.llm.file_alias import get_registry
		from idp.idp.llm.message_renderer import render_history, render_user_message
		from idp.idp.llm.prompts import build_chat_system_prompt
		from idp.idp.llm.tools.base import ToolContext
		from idp.idp.llm.tools.registry import dispatch, get_provider_schemas, load_tool_registry

		client = self._client or LLMClient.from_settings()
		conversation = frappe.get_doc("IDP Conversation", self.conversation_id)
		ctx = ToolContext(
			conversation_id=self.conversation_id,
			user=frappe.session.user if hasattr(frappe, "session") else "Administrator",
			company=conversation.get("company"),
			output_language=conversation.get("output_language") or "English",
			target_doctype=conversation.get("target_doctype"),
		)

		# Make sure the registry is loaded once per request.
		load_tool_registry()
		registry = get_registry(self.conversation_id)

		new_messages: list[dict] = []

		# 1. Register attachments + persist user message ----------------------
		if attachments:
			for a in attachments:
				registry.register(
					file_url=a.get("file_url") or "",
					file_name=a.get("file_name") or "",
					mime_type=a.get("mime_type") or "",
					tabfile_name=a.get("tabfile_name"),
					file_size=a.get("file_size"),
				)
			registry.persist()

		if (user_message is not None and user_message.strip()) or attachments:
			user_msg_doc = self._persist_message(
				role="user",
				content=user_message or "",
				attachments=attachments or [],
			)
			new_messages.append(user_msg_doc)
			self._publish_event(
				"idp_conversation_message",
				{"conversation": self.conversation_id, "message": user_msg_doc},
			)

		# Inject user confirmation (Phase 20 Submit button click).
		if user_confirmed_action:
			ack = self._persist_message(
				role="tool",
				content=json.dumps({"user_confirmed": True, "action": user_confirmed_action}),
				tool_name="user_confirmation",
				tool_arguments=user_confirmed_action,
				tool_result={"success": True, "user_confirmed": True},
			)
			new_messages.append(ack)

		# 2. Loop -------------------------------------------------------------
		schemas = get_provider_schemas(names=[t for t in self._tool_names_for_llm()] or None)
		system_prompt = build_chat_system_prompt(
			target_doctype=ctx.target_doctype,
			company=ctx.company,
			output_language=ctx.output_language,
		)
		supports_vision = client.supports("vision")
		supports_tools = client.supports("tools")
		stop_reason = "max_iterations"
		iterations = 0
		agg_in = agg_out = 0
		agg_cost = 0.0

		for iterations in range(1, self.max_iterations + 1):
			persisted = self._fetch_history()
			# Render history through the same registry the user sees.
			messages = [{"role": "system", "content": system_prompt}]
			messages.extend(render_history(persisted, registry, supports_vision=supports_vision))

			self._publish_event(
				"idp_conversation_thinking",
				{
					"conversation": self.conversation_id,
					"iteration": iterations,
				},
			)
			t0 = time.time()
			response = client.chat(
				messages=messages,
				tools=schemas if supports_tools else None,
				tool_choice="auto" if supports_tools else None,
				user=ctx.user,
			)
			latency_ms = int((time.time() - t0) * 1000)
			usage = getattr(response, "usage", None)
			cost_usd = float((response.raw or {}).get("_idp_cost_usd") or 0.0)
			tokens_in = int(getattr(usage, "prompt", 0)) if usage else 0
			tokens_out = int(getattr(usage, "completion", 0)) if usage else 0
			agg_in += tokens_in
			agg_out += tokens_out
			agg_cost += cost_usd

			# 3. Persist assistant message --------------------------------
			tool_calls = list(getattr(response, "tool_calls", None) or [])
			assistant_msg = self._persist_message(
				role="assistant",
				content=response.content or "",
				latency_ms=latency_ms,
				tokens_in=tokens_in,
				tokens_out=tokens_out,
				tool_call_id=tool_calls[0].call_id if tool_calls else None,
				tool_name=tool_calls[0].name if tool_calls else None,
				tool_arguments=tool_calls[0].arguments if tool_calls else None,
			)
			new_messages.append(assistant_msg)
			self._publish_event(
				"idp_conversation_message",
				{"conversation": self.conversation_id, "message": assistant_msg},
			)

			if not tool_calls:
				stop_reason = "no_tool_calls"
				break

			# 4. Dispatch each tool call ----------------------------------
			stop_loop = False
			for call in tool_calls:
				tool_name = call.name
				args = call.arguments or {}
				self._publish_event(
					"idp_conversation_tool_start",
					{
						"conversation": self.conversation_id,
						"name": tool_name,
						"arguments": args,
						"call_id": call.call_id,
					},
				)
				t_start = time.time()
				result = dispatch(tool_name, args, ctx)
				duration_ms = int((time.time() - t_start) * 1000)
				self._publish_event(
					"idp_conversation_tool_end",
					{
						"conversation": self.conversation_id,
						"name": tool_name,
						"call_id": call.call_id,
						"success": result.success,
						"stop_processing": result.stop_processing,
						"duration_ms": duration_ms,
					},
				)
				tool_msg = self._persist_message(
					role="tool",
					content=json.dumps(result.to_dict(), default=str),
					tool_call_id=call.call_id,
					tool_name=tool_name,
					tool_arguments=args,
					tool_result=result.to_dict(),
					rendered_card_payload=result.card,
					rendered_card_type=(result.card or {}).get("card_type")
					if isinstance(result.card, dict)
					else None,
					stop_processing=bool(result.stop_processing),
					error=result.error if not result.success else None,
				)
				new_messages.append(tool_msg)
				self._publish_event(
					"idp_conversation_message",
					{"conversation": self.conversation_id, "message": tool_msg},
				)

				if result.stop_processing:
					stop_reason = (
						f"stop_on_error:{result.error_code}" if not result.success else "stop_on_tool"
					)
					stop_loop = True
					if not result.success:
						self._publish_event(
							"idp_conversation_error",
							{
								"conversation": self.conversation_id,
								"error": result.error,
								"error_code": result.error_code,
								"stop_processing": True,
							},
						)
					break

			if stop_loop:
				break

		# 5. Refresh denormalised counters -----------------------------------
		try:
			conversation.reload()
			conversation.refresh_stats()
			conversation.db_update()
		except Exception:
			logger.exception("failed to refresh conversation stats")

		self._publish_event(
			"idp_conversation_complete",
			{
				"conversation": self.conversation_id,
				"total_iterations": iterations,
				"stop_reason": stop_reason,
				"tokens_in": agg_in,
				"tokens_out": agg_out,
				"cost_usd": agg_cost,
			},
		)
		return AgentRunResult(
			conversation_id=self.conversation_id,
			new_messages=new_messages,
			iterations=iterations,
			stop_reason=stop_reason,
			tokens_in=agg_in,
			tokens_out=agg_out,
			cost_usd=agg_cost,
		)

	# ------------------------------------------------------------------ helpers

	def _tool_names_for_llm(self) -> list[str]:
		"""Return tool names to advertise to the LLM (filters hidden_tools)."""

		from idp.idp.llm.tools.registry import list_tools

		hidden = set(self.hidden_tools)
		return [t.name for t in list_tools() if t.name not in hidden]

	def _fetch_history(self) -> list[dict]:
		"""Return the conversation's persisted messages ordered by sequence."""

		import frappe

		rows = frappe.get_all(
			"IDP Message",
			filters={"conversation": self.conversation_id},
			fields=[
				"name",
				"role",
				"content",
				"sequence",
				"tool_call_id",
				"tool_name",
				"tool_arguments",
				"tool_result",
				"attachments",
				"rendered_card_type",
				"rendered_card_payload",
				"stop_processing",
			],
			order_by="sequence asc",
			limit_page_length=0,
		)
		# Stringified JSON columns → dict for the renderer.
		for r in rows:
			for col in ("tool_arguments", "tool_result", "attachments", "rendered_card_payload"):
				val = r.get(col)
				if isinstance(val, str) and val.strip():
					try:
						r[col] = json.loads(val)
					except json.JSONDecodeError:
						pass
		return rows

	def _persist_message(
		self,
		*,
		role: str,
		content: str,
		attachments: list[dict] | None = None,
		latency_ms: int | None = None,
		tokens_in: int | None = None,
		tokens_out: int | None = None,
		tool_call_id: str | None = None,
		tool_name: str | None = None,
		tool_arguments: dict | None = None,
		tool_result: dict | None = None,
		rendered_card_type: str | None = None,
		rendered_card_payload: dict | None = None,
		stop_processing: bool = False,
		error: str | None = None,
	) -> dict:
		"""Insert an :class:`IDPMessage` row and return its as_dict() form."""

		import frappe

		doc = frappe.new_doc("IDP Message")
		doc.conversation = self.conversation_id
		doc.role = role
		doc.content = content or ""
		if attachments is not None:
			doc.attachments = json.dumps(attachments, default=str)
		if latency_ms is not None:
			doc.latency_ms = latency_ms
		if tokens_in is not None:
			doc.tokens_in = tokens_in
		if tokens_out is not None:
			doc.tokens_out = tokens_out
		if tool_call_id:
			doc.tool_call_id = tool_call_id
		if tool_name:
			doc.tool_name = tool_name
		if tool_arguments is not None:
			doc.tool_arguments = json.dumps(tool_arguments, default=str)
		if tool_result is not None:
			doc.tool_result = json.dumps(tool_result, default=str)
		if rendered_card_type:
			doc.rendered_card_type = rendered_card_type
		if rendered_card_payload is not None:
			doc.rendered_card_payload = json.dumps(rendered_card_payload, default=str)
		if stop_processing:
			doc.stop_processing = 1
		if error:
			doc.error = error
		doc.insert(ignore_permissions=True)
		return doc.as_dict()

	def _publish_event(self, event: str, payload: dict) -> None:
		"""Publish a realtime event to the conversation's subscribers."""

		try:
			import frappe

			frappe.publish_realtime(
				event=event,
				message=payload,
				doctype="IDP Conversation",
				docname=self.conversation_id,
			)
		except Exception:
			logger.debug(f"realtime publish skipped for {event!r}", exc_info=False)


__all__ = [
	"AgentRunResult",
	"IDPAgent",
]
