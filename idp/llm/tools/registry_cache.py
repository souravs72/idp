# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""TTL cache for the per-user tool-schema list (Phase 26 §26.3).

Building the provider-tool list involves walking the registry,
checking ``IDP Tool Configuration`` per tool, and resolving the
caller's roles.  None of that varies during the lifetime of a
single chat session, so we cache the resulting schema list keyed on
``(enabled_plugin_set, enabled_tool_set, role_set)``.

Writes to ``IDP Plugin Configuration`` / ``IDP Tool Configuration``
and ``Has Role`` invalidate the entire cache via the controllers'
``on_update`` / ``on_trash`` hooks.

Default TTL is 5 minutes — matches the in-process schema cache in
:mod:`idp.core.cache`.  The hot agent-loop dispatch path is *not*
covered by this cache (each tool is dispatched individually anyway),
so the optimisation is strictly for ``tools/list`` /
``list_agent_tools`` lookups that the chatbot UI hits on every
conversation open.
"""

from __future__ import annotations

import hashlib
import json

from idp.core.cache import cache_delete, cache_get, cache_set
from idp.core.logger import get_logger

logger = get_logger("idp.llm.tools.registry_cache")

_KEY_PREFIX = "idp:tool_registry:"
_INDEX_KEY = "idp:tool_registry:_index"
_TTL_SECONDS = 300.0  # §26.3 default


# ---------------------------------------------------------------------------
# Key building
# ---------------------------------------------------------------------------


def _build_cache_key(
    *,
    enabled_plugins: list[str],
    enabled_tools: list[str],
    user_roles: list[str],
    name_filter: list[str] | None,
) -> str:
    payload = {
        "p": sorted(set(enabled_plugins or [])),
        "t": sorted(set(enabled_tools or [])),
        "r": sorted(set(user_roles or [])),
        "f": sorted(set(name_filter or [])) if name_filter is not None else None,
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()[:24]
    return f"{_KEY_PREFIX}{digest}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_cached_schemas(
    *,
    enabled_plugins: list[str],
    enabled_tools: list[str],
    user_roles: list[str],
    name_filter: list[str] | None,
) -> list[dict] | None:
    """Return cached schemas for the given context, or ``None``."""

    key = _build_cache_key(
        enabled_plugins=enabled_plugins,
        enabled_tools=enabled_tools,
        user_roles=user_roles,
        name_filter=name_filter,
    )
    return cache_get(key)


def set_cached_schemas(
    schemas: list[dict],
    *,
    enabled_plugins: list[str],
    enabled_tools: list[str],
    user_roles: list[str],
    name_filter: list[str] | None,
) -> None:
    """Store *schemas* under the (plugins, tools, roles, filter) key."""

    key = _build_cache_key(
        enabled_plugins=enabled_plugins,
        enabled_tools=enabled_tools,
        user_roles=user_roles,
        name_filter=name_filter,
    )
    cache_set(key, list(schemas), ttl_seconds=_TTL_SECONDS)
    # Track the key in an index so we can flush in one shot on invalidation.
    index = cache_get(_INDEX_KEY) or []
    if key not in index:
        index = list(index) + [key]
        cache_set(_INDEX_KEY, index, ttl_seconds=_TTL_SECONDS)


def invalidate_tool_registry_cache() -> None:
    """Drop every cached schema list.

    Called from ``IDP Plugin Configuration`` and ``IDP Tool
    Configuration`` write hooks, and also when ``Has Role`` rows
    change.
    """

    index = cache_get(_INDEX_KEY) or []
    for key in index:
        cache_delete(key)
    cache_delete(_INDEX_KEY)


__all__ = [
    "get_cached_schemas",
    "invalidate_tool_registry_cache",
    "set_cached_schemas",
]
