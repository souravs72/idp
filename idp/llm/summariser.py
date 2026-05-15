# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 28 G4 — Sliding-window conversation summariser.

Goal: when the persisted message history grows past
``IDP Settings.summarise_after_messages`` (default 8), compress every
message *older* than the most recent ``keep_recent`` (also configurable
indirectly) into a single ~200-token digest.  The digest is cached on
``IDP Conversation.summary_digest`` and the boundary on
``IDP Conversation.summary_up_to_seq`` so subsequent turns reuse the
same digest instead of re-summarising the same prefix every time.

Returned shape (consumed by :class:`IDPAgent.run`)::

	{
	    "digest": "<string OR empty>",     # newline-joined plaintext
	    "up_to_seq": <int>,                # highest IDPMessage.sequence covered
	    "tail": [<row>, ...],              # rows the agent must render verbatim
	    "stats": {"summarised": int, "kept": int},
	}

The summariser deliberately never touches **tool**-role rows that pair
with the current assistant turn's ``tool_calls`` — that would break
Anthropic's strict ``tool_use_id`` ↔ ``tool_result`` invariant.  It
folds only complete user/assistant pairs from the head of the history.
"""

from __future__ import annotations

from typing import Any

from idp.core.cache import cache_get, cache_set
from idp.core.logger import get_logger

logger = get_logger("idp.llm.summariser")

# Defaults match the roadmap.  Both are overridable from IDP Settings.
_DEFAULT_SUMMARISE_AFTER = 8
_DEFAULT_KEEP_RECENT = 4  # always render the last N rows verbatim
_DEFAULT_DIGEST_TARGET_TOKENS = 200
# In-memory dedup cache so repeated agent loops within the same request
# don't re-summarise the same prefix.  TTL is short — the persisted
# ``IDP Conversation.summary_digest`` field is the durable cache.
_SUMMARY_CACHE_TTL_SECONDS = 600.0


def _read_summariser_settings() -> tuple[int, int]:
	"""Return ``(summarise_after, keep_recent)`` from IDP Settings."""

	try:
		import frappe
	except ImportError:
		return _DEFAULT_SUMMARISE_AFTER, _DEFAULT_KEEP_RECENT
	try:
		summarise_after = int(
			frappe.db.get_single_value("IDP Settings", "summarise_after_messages")
			or _DEFAULT_SUMMARISE_AFTER
		)
	except Exception:
		summarise_after = _DEFAULT_SUMMARISE_AFTER
	# Keep-recent isn't a separate field — derive a sensible value from
	# the summarise_after threshold so the tail still has context.
	keep_recent = max(_DEFAULT_KEEP_RECENT, summarise_after // 2)
	return max(summarise_after, 1), max(keep_recent, 1)


def _row_seq(row: dict) -> int:
	try:
		return int(row.get("sequence") or 0)
	except (TypeError, ValueError):
		return 0


def _is_summarisable_role(row: dict) -> bool:
	"""Tool rows are kept verbatim — folding them would orphan their tool_use_id."""

	return row.get("role") in {"user", "assistant"}


def _format_row_for_digest(row: dict) -> str:
	role = (row.get("role") or "").upper()
	content = (row.get("content") or "").strip()
	if not content:
		return ""
	# Hard cap per row so any one runaway turn can't dominate the prompt.
	if len(content) > 600:
		content = content[:600].rstrip() + "…"
	return f"{role}: {content}"


def _build_digest_prompt(head_rows: list[dict], target_tokens: int) -> list[dict]:
	"""Build the cheap-tier chat-completion prompt for the digest."""

	body_lines: list[str] = []
	for r in head_rows:
		line = _format_row_for_digest(r)
		if line:
			body_lines.append(line)
	body = "\n".join(body_lines) if body_lines else "(no content)"
	system = (
		"You are a conversation summariser.  Compress the dialogue below "
		f"into approximately {target_tokens} tokens of plain English.  "
		"Preserve: who the user is talking about (companies, suppliers, "
		"document types), every decision already taken, every value the "
		"user confirmed or rejected, and any open question.  Drop greetings, "
		"acknowledgements, and intermediate tool-call mechanics.  Do NOT "
		"invent details that are not in the dialogue."
	)
	return [
		{"role": "system", "content": system},
		{"role": "user", "content": body},
	]


def maybe_summarise(
	*,
	conversation_id: str,
	rows: list[dict],
	llm_client: Any,
) -> dict:
	"""Return a summarisation envelope for *rows*.

	* If the message count is below the configured threshold, returns
	  ``{"digest": "", "up_to_seq": existing, "tail": rows, "stats": …}``
	  unchanged so the renderer falls through to its normal path.
	* Otherwise folds the head of *rows* into a digest, caches the
	  result on the IDP Conversation row, and returns the
	  ``(digest, up_to_seq, tail)`` triple.

	The summariser is *best effort*: any LLM failure, missing field, or
	Frappe import error degrades gracefully to "no digest, render
	everything verbatim".  It must never break the agent loop.
	"""

	summarise_after, keep_recent = _read_summariser_settings()
	if len(rows) <= summarise_after:
		return {
			"digest": "",
			"up_to_seq": 0,
			"tail": rows,
			"stats": {"summarised": 0, "kept": len(rows)},
		}

	# Tail = the last keep_recent rows + any tool rows that share the
	# same assistant.  We approximate by always keeping the last
	# ``keep_recent`` rows verbatim; tool rows in that window stay too.
	tail = rows[-keep_recent:]
	head = rows[:-keep_recent]
	# Of the head, only user/assistant rows go into the digest.  Tool
	# rows in the head are dropped (their tool_use_id can no longer be
	# paired with an in-window tool_use, so they would be rejected by
	# Anthropic anyway).
	digestible = [r for r in head if _is_summarisable_role(r)]
	if not digestible:
		return {
			"digest": "",
			"up_to_seq": 0,
			"tail": rows,
			"stats": {"summarised": 0, "kept": len(rows)},
		}

	up_to_seq = max((_row_seq(r) for r in head), default=0)

	# 1. Try the persisted Conversation cache first.
	persisted_digest, persisted_seq = _load_persisted_digest(conversation_id)
	if persisted_digest and persisted_seq >= up_to_seq:
		return {
			"digest": persisted_digest,
			"up_to_seq": persisted_seq,
			"tail": [r for r in rows if _row_seq(r) > persisted_seq],
			"stats": {"summarised": len(digestible), "kept": len(tail), "source": "persisted"},
		}

	# 2. Try the in-process cache (same request, multiple agent loops).
	mem_key = f"idp:summary:{conversation_id}:{up_to_seq}"
	mem_hit = cache_get(mem_key)
	if mem_hit:
		return {
			"digest": mem_hit,
			"up_to_seq": up_to_seq,
			"tail": tail,
			"stats": {"summarised": len(digestible), "kept": len(tail), "source": "memory"},
		}

	# 3. Call the cheap-tier model for a fresh digest.
	digest_text = _call_summariser_llm(digestible, llm_client)
	if not digest_text:
		# LLM unavailable — fall back to verbatim rendering of everything.
		return {
			"digest": "",
			"up_to_seq": 0,
			"tail": rows,
			"stats": {"summarised": 0, "kept": len(rows), "source": "llm_unavailable"},
		}

	# 4. Persist + memo so future turns reuse the same digest.
	cache_set(mem_key, digest_text, ttl_seconds=_SUMMARY_CACHE_TTL_SECONDS)
	_persist_digest(conversation_id, digest_text, up_to_seq)

	return {
		"digest": digest_text,
		"up_to_seq": up_to_seq,
		"tail": tail,
		"stats": {"summarised": len(digestible), "kept": len(tail), "source": "fresh"},
	}


def _call_summariser_llm(rows: list[dict], llm_client: Any) -> str:
	"""Call the cheap-tier route for the digest.  Returns ``""`` on failure."""

	if llm_client is None:
		return ""
	messages = _build_digest_prompt(rows, _DEFAULT_DIGEST_TARGET_TOKENS)
	try:
		response = llm_client.chat(
			messages=messages,
			# Hint to the router that this is a low-stakes summarisation
			# call — providers that honour ``route_hint`` will send it to
			# the cheap tier configured via IDP Settings.llm_model_routes.
			route_hint="cheap",
		)
	except TypeError:
		# Older clients without ``route_hint``: just call without it.
		try:
			response = llm_client.chat(messages=messages)
		except Exception as exc:  # pragma: no cover - defensive
			logger.warning(f"summariser LLM call failed: {exc}")
			return ""
	except Exception as exc:  # pragma: no cover - defensive
		logger.warning(f"summariser LLM call failed: {exc}")
		return ""
	content = getattr(response, "content", None) or ""
	return content.strip()


def _load_persisted_digest(conversation_id: str) -> tuple[str, int]:
	"""Read the durable ``(digest, up_to_seq)`` pair from IDP Conversation."""

	try:
		import frappe
	except ImportError:
		return "", 0
	try:
		row = frappe.db.get_value(
			"IDP Conversation",
			conversation_id,
			["summary_digest", "summary_up_to_seq"],
			as_dict=True,
		) or {}
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"summariser durable-cache read failed: {exc}")
		return "", 0
	digest = (row.get("summary_digest") or "").strip()
	try:
		seq = int(row.get("summary_up_to_seq") or 0)
	except (TypeError, ValueError):
		seq = 0
	return digest, seq


def _persist_digest(conversation_id: str, digest: str, up_to_seq: int) -> None:
	"""Write ``(digest, up_to_seq)`` back to IDP Conversation."""

	try:
		import frappe
	except ImportError:
		return
	try:
		frappe.db.set_value(
			"IDP Conversation",
			conversation_id,
			{"summary_digest": digest, "summary_up_to_seq": up_to_seq},
			update_modified=False,
		)
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"summariser durable-cache write failed: {exc}")


def render_digest_as_system_note(digest: str) -> dict | None:
	"""Return a ``system``-role message dict carrying the digest.

	The agent inserts this *after* the main system prompt so the LLM
	sees the summary as additional context rather than instructions.
	Returns ``None`` when the digest is empty.
	"""

	if not digest:
		return None
	return {
		"role": "system",
		"content": (
			"Earlier conversation digest (summarised — older messages were "
			"compressed to save tokens):\n" + digest
		),
	}


__all__ = [
	"maybe_summarise",
	"render_digest_as_system_note",
]
