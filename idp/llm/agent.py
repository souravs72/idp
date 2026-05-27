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

		from idp.llm import cancellation as _cancel
		from idp.llm.client import LLMClient
		from idp.llm.file_alias import get_registry
		from idp.llm.message_renderer import render_history, render_user_message
		from idp.llm.prompts import build_chat_system_prompt
		from idp.llm.providers.base import StreamDelta
		from idp.llm.summariser import maybe_summarise, render_digest_as_system_note
		from idp.tools.base import ToolContext
		from idp.tools.registry import dispatch, get_provider_schemas, load_tool_registry

		client = self._client or LLMClient.from_settings()
		conversation = frappe.get_doc("IDP Conversation", self.conversation_id)
		ctx = ToolContext(
			conversation_id=self.conversation_id,
			user=frappe.session.user if hasattr(frappe, "session") else "Administrator",
			company=conversation.get("company"),
			output_language=conversation.get("output_language") or "English",
			target_doctype=conversation.get("target_doctype"),
			ocr_language=conversation.get("ocr_language") or None,
		)

		# Make sure the registry is loaded once per request.  Phase 26
		# §26.1: also register tools contributed by enabled plugins
		# (third-party ``idp_tools`` / ``idp_plugins`` hooks).
		load_tool_registry()
		try:
			from idp.plugins.loader import register_plugin_tools

			register_plugin_tools()
		except Exception:
			logger.debug("plugin tool registration skipped", exc_info=True)
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
		#
		# We persist this as a *user*-role message rather than a
		# synthetic ``tool`` row so we don't have to fabricate a
		# ``tool_call_id`` that pairs with a prior assistant
		# ``tool_use``.  Anthropic strictly validates that every
		# ``tool_result.tool_use_id`` references an upstream ``tool_use``
		# block whose id matches the regex ``^[a-zA-Z0-9_-]+$``; an
		# orphan / empty id raises a 400 (Phase 24 fix).
		#
		# A plain user-role JSON line is enough for the LLM to recognise
		# the confirmation and proceed to ``create_document`` — the
		# previously-shown ConfirmationCard already supplies the data,
		# and the system prompt tells the model to call ``create_document``
		# once the user confirms.
		if user_confirmed_action:
			ack_payload = {"user_confirmed": True, "action": user_confirmed_action}
			ack = self._persist_message(
				role="user",
				content="[user_confirmed_action] " + json.dumps(ack_payload, default=str),
				tool_name="user_confirmation",
				tool_arguments=user_confirmed_action,
			)
			new_messages.append(ack)

		# 2. Loop -------------------------------------------------------------
		# Phase 26 §26.2 — filter the schema list by the caller's
		# ``IDP Tool Configuration`` permissions so the LLM never sees
		# tools it cannot invoke.
		schemas = get_provider_schemas(
			names=[t for t in self._tool_names_for_llm()] or None,
			user=ctx.user,
		)
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

		# Phase 28 — read renderer-level token-efficiency flags once per
		# request.  ``get_single_value`` returns ``None`` for unknown
		# fields (older installs without the patch applied), so we fall
		# back to the documented defaults.
		try:
			page_pre_pass_enabled = bool(
				frappe.db.get_single_value("IDP Settings", "page_pre_pass_enabled")
			)
		except Exception:
			page_pre_pass_enabled = True
		try:
			strip_thinking_blocks = bool(
				frappe.db.get_single_value("IDP Settings", "strip_thinking_blocks")
			)
		except Exception:
			strip_thinking_blocks = True
		# Phase 30 — opt-in token streaming.  When disabled we keep the
		# legacy ``provider.chat()`` path so the audit-trail is identical
		# to pre-Phase-30 behaviour.
		try:
			streaming_enabled = bool(
				frappe.db.get_single_value("IDP Settings", "streaming_enabled")
			)
		except Exception:
			streaming_enabled = True
		# Mutable accumulator the renderer fills in across all attachments
		# rendered this turn.  Surfaced to the IDP Document Log row below.
		page_pre_pass_stats: dict[str, int] = {}

		# Phase 30 — register a cancellation token for this run.  The
		# ``cancel_turn`` HTTP endpoint flips this flag; both the
		# streaming branch and the iteration boundary poll it.
		cancel_token = _cancel.register(self.conversation_id)

		for iterations in range(1, self.max_iterations + 1):
			persisted = self._fetch_history()
			# Phase 28 G4 — slide a digest over older messages once we
			# cross the configurable threshold.  The summariser is
			# best-effort: any failure degrades to verbatim rendering.
			summary = maybe_summarise(
				conversation_id=self.conversation_id,
				rows=persisted,
				llm_client=client,
			)
			render_rows = summary.get("tail") or persisted
			# Render history through the same registry the user sees.
			messages = [{"role": "system", "content": system_prompt}]
			digest_msg = render_digest_as_system_note(summary.get("digest") or "")
			if digest_msg:
				messages.append(digest_msg)
			messages.extend(
				render_history(
					render_rows,
					registry,
					supports_vision=supports_vision,
					target_doctype=ctx.target_doctype,
					page_pre_pass_enabled=page_pre_pass_enabled,
					page_pre_pass_stats=page_pre_pass_stats,
					strip_thinking_blocks=strip_thinking_blocks,
				)
			)

			# Honour any cancellation requested between rounds.
			if cancel_token.cancelled:
				stop_reason = f"cancelled:{cancel_token.reason or 'user_requested'}"
				break

			self._publish_event(
				"idp_conversation_thinking",
				{
					"conversation": self.conversation_id,
					"iteration": iterations,
				},
			)
			t0 = time.time()
			use_streaming = streaming_enabled and supports_tools  # tools also work via stream
			cancelled_mid_stream = False
			if use_streaming:
				response = self._stream_round(
					client=client,
					messages=messages,
					tools=schemas if supports_tools else None,
					tool_choice="auto" if supports_tools else None,
					user=ctx.user,
					iteration=iterations,
					cancel_token=cancel_token,
				)
				if response is None:
					# Cancellation observed mid-stream — persist partial
					# assistant text (if any) with status=cancelled and
					# break out of the iteration loop.
					cancelled_mid_stream = True
			else:
				response = client.chat(
					messages=messages,
					tools=schemas if supports_tools else None,
					tool_choice="auto" if supports_tools else None,
					user=ctx.user,
				)
			latency_ms = int((time.time() - t0) * 1000)
			if cancelled_mid_stream:
				stop_reason = f"cancelled:{cancel_token.reason or 'user_requested'}"
				# Persist whatever buffered content the streamer captured
				# so the user sees their partial reply in the transcript.
				partial = getattr(self, "_last_stream_buffer", "") or ""
				self._persist_message(
					role="assistant",
					content=partial,
					latency_ms=latency_ms,
					status="cancelled",
				)
				break
			usage = getattr(response, "usage", None)
			cost_usd = float((response.raw or {}).get("_idp_cost_usd") or 0.0)
			tokens_in = int(getattr(usage, "prompt", 0)) if usage else 0
			tokens_out = int(getattr(usage, "completion", 0)) if usage else 0
			agg_in += tokens_in
			agg_out += tokens_out
			agg_cost += cost_usd

			# 3. Persist assistant message --------------------------------
			tool_calls = list(getattr(response, "tool_calls", None) or [])
			# Persist the full tool_calls array so multi-tool-call turns
			# can round-trip back to the LLM with all tool_use_ids intact.
			# The legacy single tool_call_id/name/arguments fields are kept
			# in sync with the first call for backward-compat with the UI
			# and any consumer that hasn't migrated to the new field.
			tool_calls_payload = (
				[
					{
						"id": c.call_id,
						"name": c.name,
						"arguments": c.arguments or {},
					}
					for c in tool_calls
				]
				if tool_calls
				else None
			)
			assistant_msg = self._persist_message(
				role="assistant",
				content=response.content or "",
				latency_ms=latency_ms,
				tokens_in=tokens_in,
				tokens_out=tokens_out,
				tool_call_id=tool_calls[0].call_id if tool_calls else None,
				tool_name=tool_calls[0].name if tool_calls else None,
				tool_arguments=tool_calls[0].arguments if tool_calls else None,
				tool_calls=tool_calls_payload,
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

				# Phase 26 §26.5 — sanitised audit row tied back to the
				# persisted ``IDP Message`` row.  Failures are swallowed
				# inside log_tool_call so the agent loop never breaks.
				try:
					from idp.tools.audit import log_tool_call

					log_tool_call(
						conversation_id=self.conversation_id,
						message_id=tool_msg.get("name") if isinstance(tool_msg, dict) else None,
						user=ctx.user,
						tool_name=tool_name,
						plugin_name=None,
						arguments=args,
						result=result.to_dict(),
						success=bool(result.success),
						error_code=result.error_code,
						error_message=result.error,
						latency_ms=duration_ms,
					)
				except Exception:
					logger.debug("audit log insert failed", exc_info=True)

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
					else:
						# Card-as-terminal: synthesise the assistant's final
						# user-facing reply from the card payload itself
						# instead of paying for another LLM round-trip just
						# to paraphrase data we already rendered.  See
						# ``propose_create_document`` and ``create_document``
						# for the contract.
						self._maybe_emit_terminal_assistant_message(
							tool_name=tool_name,
							card=result.card,
							new_messages=new_messages,
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

		# Phase 30 — release the cancellation token; we're past every
		# point that polls it.  ``run_agent`` also calls deregister in
		# its except branch when ``run()`` raises before we get here.
		_cancel.deregister(self.conversation_id)

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
		"""Return tool names to advertise to the LLM (filters hidden_tools).

		Also strips ``validate_document`` when
		``IDP Settings.enable_pre_validation`` is off — admins who turn
		pre-validation off don't want the agent calling the validator
		as an LLM tool either.
		"""

		from idp.tools.registry import list_tools

		hidden = set(self.hidden_tools)
		try:
			from idp.core.config import is_feature_enabled

			if not is_feature_enabled("enable_pre_validation"):
				hidden.add("validate_document")
		except Exception:
			pass
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
				"tool_calls",
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
			for col in (
				"tool_arguments",
				"tool_calls",
				"tool_result",
				"attachments",
				"rendered_card_payload",
			):
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
		tool_calls: list[dict] | None = None,
		tool_result: dict | None = None,
		rendered_card_type: str | None = None,
		rendered_card_payload: dict | None = None,
		stop_processing: bool = False,
		error: str | None = None,
		status: str | None = None,
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
		if tool_calls is not None:
			doc.tool_calls = json.dumps(tool_calls, default=str)
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
		if status:
			# Field added in Phase 30 — older installs without the
			# migration patch tolerate the attribute silently because
			# Frappe Documents accept arbitrary attribute writes.
			try:
				doc.status = status
			except Exception:
				pass
		doc.insert(ignore_permissions=True)
		return doc.as_dict()

	def _maybe_emit_terminal_assistant_message(
		self,
		*,
		tool_name: str,
		card: dict | None,
		new_messages: list[dict],
	) -> None:
		"""Synthesise a final assistant message from a terminal tool's card.

		Tools like ``propose_create_document`` and ``create_document``
		mark their result with ``stop_processing=True`` because the card
		payload already contains all the user-facing text the chat needs
		to show.  Rather than letting the agent iterate one more time
		just so the LLM can paraphrase that card, we synthesise the
		assistant's reply deterministically here.

		The persisted message carries:

		* ``role="assistant"`` so the UI renders it as a regular reply.
		* ``content`` taken from ``card.summary`` (ConfirmationCard) or
		  ``card.body`` (InfoCard).

		For ``ConfirmationCard`` we deliberately do NOT re-attach the
		card payload here because the *tool*-role message that produced
		it already carries ``rendered_card_payload`` and the UI renders
		that as the interactive card.  Re-attaching would result in two
		identical cards appearing in the chat (Phase 24 fix).

		For ``InfoCard`` we also drop the payload — the body text is
		sufficient and the renderer doesn't need a second copy.
		"""

		if not isinstance(card, dict):
			return

		card_type = card.get("card_type")
		if card_type == "ConfirmationCard":
			content = card.get("summary") or ""
		elif card_type == "InfoCard":
			title = card.get("title") or ""
			body = card.get("body") or ""
			content = f"{title}\n\n{body}".strip() if title and body else (title or body)
		else:
			# Unknown card type — let the LLM iterate normally.  We
			# reach this only when a third-party tool starts setting
			# stop_processing=True without following the contract.
			return

		if not content:
			return

		# Synthesise text-only assistant reply.  The tool-role row that
		# fired this terminal turn already owns the card payload, so
		# attaching it again here would render two cards in the chat.
		final_msg = self._persist_message(
			role="assistant",
			content=content,
		)
		new_messages.append(final_msg)
		self._publish_event(
			"idp_conversation_message",
			{"conversation": self.conversation_id, "message": final_msg},
		)
		logger.debug(
			f"agent emitted terminal assistant message from {tool_name} ({card_type})"
		)

	def _stream_round(
		self,
		*,
		client: Any,
		messages: list[dict],
		tools: list[dict] | None,
		tool_choice: str | dict | None,
		user: str,
		iteration: int,
		cancel_token: Any,
	) -> Any:
		"""Drive a single LLM round via :meth:`LLMClient.stream_chat`.

		Publishes ``idp_conversation_token`` events as text deltas arrive
		and returns the fully-assembled :class:`LLMResponse` from the
		stream's terminal ``final`` delta.  When the caller's cancellation
		token flips mid-stream we return ``None`` and stash the partial
		text on ``self._last_stream_buffer`` so the agent loop can persist
		it under ``status="cancelled"``.

		Errors surfaced via ``StreamDelta(kind="error", ...)`` are re-
		raised so the existing ``run_agent`` error path handles them.
		"""

		buffer: list[str] = []
		message_seq = f"{self.conversation_id}:{iteration}"
		self._last_stream_buffer = ""
		# Batch realtime emits at ~50 chars to keep socket.io chatty but
		# not insane on small models.  The roadmap §Risk note covers this.
		BATCH_CHARS = 24
		pending: list[str] = []
		pending_len = 0

		def flush() -> None:
			nonlocal pending, pending_len
			if not pending:
				return
			chunk = "".join(pending)
			pending = []
			pending_len = 0
			self._publish_event(
				"idp_conversation_token",
				{
					"conversation": self.conversation_id,
					"message_seq": message_seq,
					"iteration": iteration,
					"text": chunk,
				},
			)

		final_response = None
		try:
			deltas = client.stream_chat(
				messages=messages,
				tools=tools,
				tool_choice=tool_choice or "auto",
				user=user,
			)
			for delta in deltas:
				if cancel_token.cancelled:
					flush()
					self._last_stream_buffer = "".join(buffer)
					return None
				if delta.kind == "text" and delta.text:
					buffer.append(delta.text)
					pending.append(delta.text)
					pending_len += len(delta.text)
					if pending_len >= BATCH_CHARS:
						flush()
				elif delta.kind == "tool_use_start":
					flush()
					self._publish_event(
						"idp_conversation_tool_call_start",
						{
							"conversation": self.conversation_id,
							"message_seq": message_seq,
							"tool_call_id": delta.tool_call_id,
							"tool_name": delta.tool_name,
						},
					)
				elif delta.kind == "error":
					flush()
					raise RuntimeError(delta.error or "stream error")
				elif delta.kind == "final":
					flush()
					final_response = delta.response
		finally:
			flush()
		self._last_stream_buffer = "".join(buffer)
		return final_response

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
