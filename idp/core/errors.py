# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 31 — Unified error map (G23).

A single source of truth that maps internal exception class names to a
``{user_message, recovery_action}`` envelope the chatbot UI renders
end-to-end.  The frontend never sees Python tracebacks or stack frames;
the backend continues to log internals via ``logger.exception``.

Goals:

* Every exception listed in the Phase 31 roadmap (§31.8) renders a
  friendly string and, where appropriate, a single recovery action that
  the UI can wire to a button click.
* The table is keyed by class name (string), not class objects, so this
  module stays cheap to import — no provider SDKs or LLM modules are
  loaded until somebody actually maps an error.
* The existing ``_FRIENDLY_ERROR_TABLE`` in ``idp.api.conversation``
  predates Phase 31 and stays in place as a compatibility layer; Phase
  31 adds a unified ``build_envelope`` helper that callers can use to
  short-circuit lookup without going through the conversation API.

The shape of a recovery action is intentionally minimal so the frontend
can render it as a single button without further negotiation::

    {
        "id": "reupload",        # used by the UI to wire a handler
        "label": "Re-upload",    # shown on the button
        "auto": False,           # True => UI runs it automatically
    }

A ``None`` recovery action means the error is informational only — the
UI surfaces the message but does not offer a remediation path.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Error envelope shape
# ---------------------------------------------------------------------------


# class_name -> {user_message, recovery_action}
ERROR_MAP: dict[str, dict[str, Any]] = {
	# Budget / rate-limit family.  These are recoverable in the sense
	# that the user can either wait, switch to rule-based extraction,
	# or ask the admin to raise the cap.
	"LLMBudgetExceededError": {
		"user_message": (
			"Daily AI budget reached. Falling back to rule-based "
			"extraction."
		),
		"recovery_action": {
			"id": "continue_rule_based",
			"label": "Continue",
			"auto": False,
			"secondary": {
				"id": "notify_admin",
				"label": "Notify admin",
			},
		},
	},
	"RateLimitExceededError": {
		"user_message": "Slow down a bit — catching up.",
		"recovery_action": {
			"id": "retry_backoff",
			"label": "Retry",
			"auto": True,
		},
	},
	# File alias gone missing — user must re-upload before we can retry.
	"FileAliasNotFoundError": {
		"user_message": (
			"I lost track of that attachment. Please re-upload."
		),
		"recovery_action": {
			"id": "reupload",
			"label": "Re-upload",
			"auto": False,
		},
	},
	# Provider timeouts manifest as a TimeoutError or LLMError with the
	# substring "timeout" — both map to the same auto-retry envelope.
	"TimeoutError": {
		"user_message": "AI service is slow right now. Retrying…",
		"recovery_action": {
			"id": "retry_once",
			"label": "Retry",
			"auto": True,
		},
	},
	"ProviderTimeoutError": {
		"user_message": "AI service is slow right now. Retrying…",
		"recovery_action": {
			"id": "retry_once",
			"label": "Retry",
			"auto": True,
		},
	},
	# Frappe permission errors raised inside propose_create_document /
	# create_document — no recovery action, just surface to the user.
	"PermissionError": {
		"user_message": "You don't have permission to create {doctype}.",
		"recovery_action": None,
	},
	"IDPPermissionError": {
		"user_message": "You don't have permission to access that file or record.",
		"recovery_action": None,
	},
	# ---------------------------------------------------------------
	# Phase 32 — Reversibility (Undo) friendly envelopes.  Undo only
	# fails for a small, well-defined set of reasons — every one of
	# them maps to an informational message; recovery is "open the
	# document and cancel manually" which we don't auto-wire.
	# ---------------------------------------------------------------
	"UndoWindowExpiredError": {
		"user_message": (
			"The undo window has expired. Open the document to cancel "
			"manually if needed."
		),
		"recovery_action": None,
	},
	"UndoNotEligibleError": {
		"user_message": "This action is not eligible for undo.",
		"recovery_action": None,
	},
	"UndoLinkExistsError": {
		"user_message": (
			"Cannot undo: another document references this record. "
			"Cancel the dependent record first."
		),
		"recovery_action": None,
	},
}


def build_envelope(exc: Exception, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Translate *exc* into the Phase 31 unified error envelope.

	Falls back to a generic envelope when the class is not registered
	so callers can rely on the return shape always being well-formed.

	Args:
		exc: the live exception instance.
		context: optional dict whose keys are substituted into
			``user_message`` via ``str.format``.  Unknown keys are
			silently ignored — ``user_message`` is never broken by a
			missing context value.

	Returns:
		``{class_name, user_message, recovery_action}``.
	"""

	cls_name = type(exc).__name__
	entry = ERROR_MAP.get(cls_name)
	if entry is None:
		# Substring fallback for ``timeout``-style messages so a
		# provider that subclasses ``LLMError`` without a dedicated
		# exception still gets the friendly retry envelope.
		text = str(exc).lower()
		if "timeout" in text or "timed out" in text:
			entry = ERROR_MAP["TimeoutError"]
		else:
			entry = {
				"user_message": (
					"Something went wrong while processing your "
					"request. Please try again."
				),
				"recovery_action": None,
			}

	message = entry["user_message"]
	if context:
		try:
			message = message.format(**context)
		except (KeyError, IndexError):
			# Leave the raw template alone rather than throwing — the
			# user is more likely to understand the templated string
			# than a KeyError stack.
			pass

	return {
		"class_name": cls_name,
		"user_message": message,
		"recovery_action": entry["recovery_action"],
	}


__all__ = ["ERROR_MAP", "build_envelope"]
