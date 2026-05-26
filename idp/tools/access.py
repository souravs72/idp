# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Per-tool role access checks (Phase 26 §26.2).

``ToolRegistry.dispatch`` and ``get_provider_schemas`` both consult
:func:`check_tool_access` to gate visibility/execution.  When no
``IDP Tool Configuration`` row exists the in-code ``ToolSpec`` defaults
apply (specifically ``requires_role``) — making the feature
backwards-compatible.

Resolution order for a tool::

    1. If a row exists and enabled = 0  → BLOCKED (tool hidden + reject).
    2. If denied_roles ∩ user_roles    → BLOCKED.
    3. If allowed_roles is non-empty
       and allowed_roles ∩ user_roles = ∅ → BLOCKED.
    4. Else (no row OR allowed_roles empty): fall back to
       ``ToolSpec.requires_role`` (existing behaviour).

The result is cached per ``(tool, frozenset(user_roles))`` for the
duration of a single request via :mod:`idp.core.cache`.
"""

from __future__ import annotations

from dataclasses import dataclass

from idp.core.logger import get_logger

logger = get_logger("idp.tools.access")


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> "AccessDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> "AccessDecision":
        return cls(allowed=False, reason=reason)


def check_tool_access(tool_name: str, user: str, *, requires_role: str | None = None) -> AccessDecision:
    """Return whether *user* may invoke the tool named *tool_name*.

    *requires_role* is the in-code default (``ToolSpec.requires_role``)
    used as a fallback when no ``IDP Tool Configuration`` row exists or
    its ``allowed_roles`` table is empty.
    """

    row = _load_tool_config(tool_name)
    user_roles = _user_roles(user)

    # Administrator and System Manager always pass — they need to be
    # able to fix locked-out tool tables.
    if user == "Administrator" or "System Manager" in user_roles:
        return AccessDecision.allow()

    if row is not None:
        if int(row.get("enabled") or 0) == 0:
            return AccessDecision.deny(f"tool '{tool_name}' is disabled by admin")

        denied = row.get("_denied_roles") or set()
        if denied & user_roles:
            return AccessDecision.deny(
                f"user holds a denied role for tool '{tool_name}'"
            )

        allowed = row.get("_allowed_roles") or set()
        if allowed:
            if not (allowed & user_roles):
                return AccessDecision.deny(
                    f"user lacks any allowed role for tool '{tool_name}'"
                )
            return AccessDecision.allow()

    # Fallback to ToolSpec.requires_role.
    if requires_role:
        if requires_role in user_roles:
            return AccessDecision.allow()
        return AccessDecision.deny(
            f"user lacks the required role '{requires_role}' for tool '{tool_name}'"
        )
    return AccessDecision.allow()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_tool_config(tool_name: str) -> dict | None:
    """Return the resolved configuration row for *tool_name* or ``None``.

    The dict has the JSON shape plus pre-computed ``_allowed_roles`` /
    ``_denied_roles`` sets for fast intersection.  Result is fed
    through :mod:`idp.core.cache` keyed on the tool name with a
    short TTL.
    """

    from idp.core.cache import cache_get, cache_set

    cache_key = f"idp:tool_cfg:{tool_name}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit if hit else None  # falsy sentinel allowed below

    try:
        import frappe
    except ImportError:
        return None

    try:
        if not frappe.db.exists("IDP Tool Configuration", tool_name):
            cache_set(cache_key, {}, ttl_seconds=300.0)
            return None
        doc = frappe.get_cached_doc("IDP Tool Configuration", tool_name)
    except Exception:
        # DocType missing (pre-migrate) or DB unavailable — fall back.
        return None

    allowed = {r.role for r in (doc.get("allowed_roles") or []) if r.role}
    denied = {r.role for r in (doc.get("denied_roles") or []) if r.role}
    row = {
        "tool_name": doc.tool_name,
        "enabled": int(doc.enabled or 0),
        "requires_confirmation": int(doc.requires_confirmation or 0),
        "_allowed_roles": allowed,
        "_denied_roles": denied,
    }
    cache_set(cache_key, row, ttl_seconds=300.0)
    return row


def _user_roles(user: str) -> set[str]:
    try:
        import frappe
    except ImportError:
        return set()
    try:
        return set(frappe.get_roles(user))
    except Exception:
        return set()


def invalidate_tool_config_cache(tool_name: str | None = None) -> None:
    """Drop the cached configuration for *tool_name* (or every tool)."""

    from idp.core.cache import _store, _lock  # noqa: WPS437 — internal flush

    prefix = "idp:tool_cfg:"
    with _lock:
        if tool_name:
            _store.pop(prefix + tool_name, None)
        else:
            for key in [k for k in list(_store.keys()) if k.startswith(prefix)]:
                _store.pop(key, None)


__all__ = ["AccessDecision", "check_tool_access", "invalidate_tool_config_cache"]
