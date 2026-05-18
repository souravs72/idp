# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Per-conversation cancellation registry (Phase 30).

The streaming branch of :class:`idp.llm.agent.IDPAgent` checks the
shared :class:`CancellationToken` in two places: before each LLM
round and on every streamed delta.  The :func:`request_cancel`
function is invoked from the ``cancel_turn`` HTTP endpoint and flips
the token's flag — there is no callback or signal, just a boolean the
producer polls.

Tokens are keyed by ``conversation_id``.  A token lives only while
the agent loop holds it; once the loop terminates (success, error or
cancel) it deregisters itself.  Concurrent runs on the same
conversation are not supported by the agent contract — registering
twice replaces the prior token, so a late cancel hits whichever run
is currently active.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class CancellationToken:
	"""Thread-safe boolean flipped by :func:`request_cancel`."""

	conversation_id: str
	_cancelled: bool = False
	_reason: str | None = None

	def cancel(self, reason: str | None = None) -> None:
		self._cancelled = True
		self._reason = reason or "user_requested"

	@property
	def cancelled(self) -> bool:
		return self._cancelled

	@property
	def reason(self) -> str | None:
		return self._reason


_LOCK = threading.Lock()
_TOKENS: dict[str, CancellationToken] = {}


def register(conversation_id: str) -> CancellationToken:
	"""Register a fresh token for *conversation_id* and return it.

	Any prior token under the same id is replaced — callers expect at
	most one active run per conversation.
	"""

	token = CancellationToken(conversation_id=conversation_id)
	with _LOCK:
		_TOKENS[conversation_id] = token
	return token


def deregister(conversation_id: str) -> None:
	"""Drop the token for *conversation_id* (best-effort, idempotent)."""

	with _LOCK:
		_TOKENS.pop(conversation_id, None)


def request_cancel(conversation_id: str, *, reason: str | None = None) -> bool:
	"""Flip the cancellation flag for *conversation_id* if a run is active.

	Returns ``True`` when a token was found (and flipped), ``False``
	when there's no active run — the HTTP endpoint surfaces this so the
	UI can decide whether the cancel "took".
	"""

	with _LOCK:
		token = _TOKENS.get(conversation_id)
	if token is None:
		return False
	token.cancel(reason)
	return True


def is_cancelled(conversation_id: str) -> bool:
	"""Lightweight peek — used by tests and the streaming loop."""

	with _LOCK:
		token = _TOKENS.get(conversation_id)
	return bool(token and token.cancelled)


__all__ = [
	"CancellationToken",
	"deregister",
	"is_cancelled",
	"register",
	"request_cancel",
]
