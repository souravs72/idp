# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Tool call audit logger (Phase 26 §26.5).

Persists a sanitised :class:`IDPToolCallLog` row after every tool
dispatch — gives admins retro-analysis on which tools fail most and
which DocTypes trigger the most user edits.

All writes go through ``frappe.new_doc(...).insert(ignore_permissions=
True)``; failures are swallowed because the audit log must never
break the agent loop.
"""

from __future__ import annotations

import json
from typing import Any

from idp.core.logger import get_logger

logger = get_logger("idp.llm.tools.audit")

_MAX_EXCERPT_BYTES = 2 * 1024  # 2 KB per §26.5
_REDACTED_KEYS = frozenset(
    {
        "file_url",
        "file_content_base64",
        "image_base64",
        "pdf_base64",
        "raw_text",
        "ocr_text",
        "api_key",
        "password",
    }
)


def log_tool_call(
    *,
    conversation_id: str | None,
    message_id: str | None,
    user: str,
    tool_name: str,
    plugin_name: str | None,
    arguments: dict | None,
    result: dict | None,
    success: bool,
    error_code: str | None,
    error_message: str | None,
    latency_ms: int,
    user_confirmed_at: Any | None = None,
    user_edits: dict | None = None,
) -> str | None:
    """Insert an :class:`IDP Tool Call Log` row.  Returns the docname or
    ``None`` on failure.

    Sanitises ``arguments`` (drops large blobs and known-secret keys)
    and truncates the result payload to :data:`_MAX_EXCERPT_BYTES`.
    """

    try:
        import frappe
    except ImportError:
        return None

    try:
        doc = frappe.new_doc("IDP Tool Call Log")
        doc.conversation = conversation_id
        doc.message = message_id
        doc.user = user
        doc.tool_name = tool_name
        doc.plugin_name = plugin_name or _infer_plugin_name(tool_name)
        doc.success = 1 if success else 0
        doc.error_code = error_code
        doc.error_message = (error_message or "")[:140]
        doc.latency_ms = int(latency_ms or 0)
        doc.tool_call_args = _sanitised_json(arguments)
        doc.tool_result_excerpt = _truncate_json(result)
        if user_confirmed_at is not None:
            doc.user_confirmed_at = user_confirmed_at
        if user_edits is not None:
            doc.user_edits = _sanitised_json(user_edits)
        doc.insert(ignore_permissions=True)
        return doc.name
    except Exception:
        logger.debug("tool call audit log insert failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_plugin_name(tool_name: str) -> str:
    """Best-effort plugin lookup using the in-memory plugin map.

    Falls back to ``"core"`` for built-in tools so older rows stay
    self-describing.
    """

    try:
        from idp.plugins.loader import enabled_plugins

        for plugin in enabled_plugins():
            for spec in plugin.get_tools() or ():
                if getattr(spec, "name", None) == tool_name:
                    return plugin.name
    except Exception:
        pass
    return "core"


def _sanitised_json(payload: Any) -> str:
    """Return a JSON string with sensitive / large fields elided."""

    if payload is None:
        return ""
    cleaned = _sanitise(payload)
    try:
        return json.dumps(cleaned, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(cleaned)


def _sanitise(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated:depth>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in _REDACTED_KEYS:
                out[k] = "<redacted>"
                continue
            out[k] = _sanitise(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        # Cap long lists at 50 entries.
        cap = 50
        items = [_sanitise(v, depth + 1) for v in list(value)[:cap]]
        if len(value) > cap:
            items.append(f"<truncated:{len(value) - cap} more>")
        return items
    if isinstance(value, str) and len(value) > 1024:
        return value[:1024] + "…"
    return value


def _truncate_json(payload: Any) -> str:
    if payload is None:
        return ""
    try:
        blob = json.dumps(payload, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(payload)
    if len(blob.encode("utf-8")) <= _MAX_EXCERPT_BYTES:
        return blob
    # Truncate by characters approximately — UTF-8 safe enough for
    # the excerpt field.
    return blob[: _MAX_EXCERPT_BYTES - 1] + "…"


__all__ = ["log_tool_call"]
