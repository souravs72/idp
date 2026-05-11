# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Plugin discovery + caching (Phase 26 §26.1, §26.3).

Discovers plugins from three sources, in order:

1. The built-in :class:`idp.plugins.core_plugin.CorePlugin`.
2. ``idp_plugins`` hook entries declared in any installed app's
   ``hooks.py``.  Each entry is a dotted path to an :class:`IDPPlugin`
   subclass.
3. ``idp_tools`` hook entries — a backward-compatible shortcut for
   plugins that contribute tools without subclassing.  Each entry is
   a dotted path to a function returning ``list[ToolSpec]``; the
   loader wraps it in an anonymous :class:`IDPPlugin` keyed by the
   declaring app name.

Discovery is wrapped in ``try/except`` per entry so a broken
third-party plugin never breaks the IDP agent loop — failures are
logged and skipped.

The discovered set is cached in :mod:`idp.core.cache` keyed
``idp:plugins:discovered`` with a 5-minute TTL.  Writes to
``IDP Plugin Configuration`` invalidate the key via the DocType's
``on_update`` hook.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from idp.core.cache import cache_delete, cache_get, cache_set
from idp.core.logger import get_logger
from idp.llm.tools.base import ToolSpec
from idp.plugins.base import IDPPlugin
from idp.plugins.core_plugin import CorePlugin

logger = get_logger("idp.plugins.loader")

_DISCOVERED_CACHE_KEY = "idp:plugins:discovered"
_ENABLED_CACHE_KEY = "idp:plugins:enabled"
_CACHE_TTL_SECONDS = 300.0  # 5 min — matches §26.3


# ---------------------------------------------------------------------------
# Anonymous plugin wrapper for idp_tools hooks
# ---------------------------------------------------------------------------


@dataclass
class _AnonymousToolPlugin(IDPPlugin):
    """Adapter around a ``idp_tools`` hook that returns raw ToolSpecs."""

    _name: str = ""
    _tools: tuple[ToolSpec, ...] = ()

    def __init__(self, app_name: str, tools: Iterable[ToolSpec]) -> None:
        self._name = app_name
        self._tools = tuple(tools)
        self.name = app_name
        self.display_name = app_name
        self.version = "0.0.0"
        self.description = f"Tools contributed by `{app_name}` via the idp_tools hook."
        self.optional = True  # third-party hooks default to opt-in

    def get_tools(self) -> Iterable[ToolSpec]:  # noqa: D401
        return list(self._tools)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_plugins(*, use_cache: bool = True) -> list[IDPPlugin]:
    """Return the full set of plugins available to this site.

    Includes :class:`CorePlugin` plus any hook-declared third-party
    plugins.  Result is cached for :data:`_CACHE_TTL_SECONDS`.

    Setting ``use_cache=False`` forces a rediscovery (used by the
    DocType ``on_update`` hook).
    """

    if use_cache:
        hit = cache_get(_DISCOVERED_CACHE_KEY)
        if hit is not None:
            return list(hit)

    plugins: list[IDPPlugin] = [CorePlugin()]
    plugins.extend(_discover_from_hooks())

    # Filter unavailable plugins (e.g. missing optional deps).
    plugins = [p for p in plugins if _is_available_safe(p)]

    cache_set(_DISCOVERED_CACHE_KEY, plugins, ttl_seconds=_CACHE_TTL_SECONDS)
    return plugins


def _discover_from_hooks() -> list[IDPPlugin]:
    """Walk ``frappe.get_hooks`` for ``idp_plugins`` and ``idp_tools``.

    Each hook entry is loaded in isolation; failures are logged but
    do not abort discovery.
    """

    try:
        import frappe
    except ImportError:
        return []

    plugins: list[IDPPlugin] = []

    # ``idp_plugins`` — dotted paths to IDPPlugin subclasses ----------
    try:
        plugin_paths = frappe.get_hooks("idp_plugins") or []
    except Exception:
        logger.debug("frappe.get_hooks('idp_plugins') failed", exc_info=True)
        plugin_paths = []

    for path in plugin_paths:
        try:
            cls = frappe.get_attr(path)
            if not isinstance(cls, type) or not issubclass(cls, IDPPlugin):
                logger.warning(
                    "idp_plugins entry %r is not an IDPPlugin subclass; skipping", path
                )
                continue
            inst = cls()
            if not inst.name:
                logger.warning("idp_plugins entry %r has empty name; skipping", path)
                continue
            plugins.append(inst)
        except Exception:
            logger.exception("Failed to load idp_plugins entry %r — skipping", path)

    # ``idp_tools`` — dotted paths to functions returning [ToolSpec] --
    try:
        hooks_map = frappe.get_hooks("idp_tools") or {}
    except Exception:
        logger.debug("frappe.get_hooks('idp_tools') failed", exc_info=True)
        hooks_map = {}

    # ``get_hooks`` may return either a flat list of paths or a dict
    # mapping app_name -> list[path] depending on Frappe version.
    if isinstance(hooks_map, dict):
        items = list(hooks_map.items())
    elif isinstance(hooks_map, (list, tuple)):
        items = [("third_party", list(hooks_map))]
    else:
        items = []

    for app_name, paths in items:
        for path in paths or []:
            try:
                fn = frappe.get_attr(path)
                tools = list(fn() or [])
                tools = [t for t in tools if isinstance(t, ToolSpec)]
                if not tools:
                    continue
                plugins.append(_AnonymousToolPlugin(app_name=str(app_name), tools=tools))
            except Exception:
                logger.exception(
                    "Failed to load idp_tools entry %r from app %r — skipping",
                    path,
                    app_name,
                )

    return plugins


def _is_available_safe(plugin: IDPPlugin) -> bool:
    try:
        return bool(plugin.is_available())
    except Exception:
        logger.exception("Plugin %r is_available() raised — treating as unavailable", plugin.name)
        return False


# ---------------------------------------------------------------------------
# Enabled-set resolution
# ---------------------------------------------------------------------------


def enabled_plugins(*, use_cache: bool = True) -> list[IDPPlugin]:
    """Return the plugins that pass the ``IDP Plugin Configuration``
    gate (enabled=1 or no row for non-optional plugins).
    """

    if use_cache:
        hit = cache_get(_ENABLED_CACHE_KEY)
        if hit is not None:
            return list(hit)

    discovered = discover_plugins(use_cache=use_cache)
    config = _load_plugin_config()
    enabled: list[IDPPlugin] = []
    for p in discovered:
        row = config.get(p.name)
        if row is None:
            # No row → default to enabled for required core plugins,
            # disabled for optional third-party ones.
            if not p.optional:
                enabled.append(p)
            continue
        if int(row.get("enabled") or 0) == 1:
            enabled.append(p)

    # Stable ordering: by priority asc (lowest first), then name.
    def _priority(p: IDPPlugin) -> tuple[int, str]:
        row = config.get(p.name) or {}
        try:
            prio = int(row.get("priority") or 100)
        except (TypeError, ValueError):
            prio = 100
        return (prio, p.name)

    enabled.sort(key=_priority)
    cache_set(_ENABLED_CACHE_KEY, enabled, ttl_seconds=_CACHE_TTL_SECONDS)
    return enabled


def _load_plugin_config() -> dict[str, dict]:
    """Return ``{plugin_name: row_dict}`` from ``IDP Plugin Configuration``.

    Returns an empty dict if Frappe is not available or the DocType
    has not been migrated yet (e.g. first install).
    """

    try:
        import frappe
    except ImportError:
        return {}

    try:
        rows = frappe.get_all(
            "IDP Plugin Configuration",
            fields=["plugin_name", "enabled", "priority", "config_json"],
            limit_page_length=0,
        )
    except Exception:
        # DocType might not exist yet (pre-migrate).
        return {}

    return {r["plugin_name"]: r for r in rows if r.get("plugin_name")}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_plugin_tools() -> None:
    """Re-register every enabled plugin's tools into the live registry.

    Called once per agent run before the registry snapshot is taken.
    Tools contributed by hook-discovered plugins survive across calls
    because the registry replaces by name.
    """

    # Local import — registry imports tool modules which trigger
    # ``@tool`` decorators that populate the in-tree set.
    from idp.llm.tools.registry import load_tool_registry, register_tool

    load_tool_registry()  # ensure built-ins are present
    for plugin in enabled_plugins():
        if plugin.name == "core":
            # Core plugin's tools are already in the registry — its
            # ``get_tools`` just mirrors them.
            continue
        try:
            for spec in plugin.get_tools() or ():
                if isinstance(spec, ToolSpec) and spec.name:
                    register_tool(spec)
        except Exception:
            logger.exception(
                "Plugin %r get_tools() raised — skipping its tools", plugin.name
            )


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def invalidate_plugin_cache(*_args, **_kwargs) -> None:
    """Drop the discovered + enabled plugin caches.

    Wired into ``IDP Plugin Configuration`` / ``IDP Tool Configuration``
    / ``Has Role`` ``on_update`` / ``on_trash`` / ``after_insert``
    hooks so admin changes take effect on the next request.  The
    star-args swallow ``(doc, method)`` parameters Frappe passes when
    invoked via ``doc_events``.
    """

    cache_delete(_DISCOVERED_CACHE_KEY)
    cache_delete(_ENABLED_CACHE_KEY)
    # Per-tool config cache (§26.2) keyed on tool name.
    try:
        from idp.llm.tools.access import invalidate_tool_config_cache

        invalidate_tool_config_cache()
    except Exception:
        logger.debug("access.invalidate_tool_config_cache unavailable", exc_info=True)
    # Tool-registry filter cache (§26.3) also keys on enabled set.
    try:
        from idp.llm.tools.registry_cache import invalidate_tool_registry_cache

        invalidate_tool_registry_cache()
    except Exception:
        logger.debug("registry_cache.invalidate_tool_registry_cache unavailable", exc_info=True)


__all__ = [
    "discover_plugins",
    "enabled_plugins",
    "invalidate_plugin_cache",
    "register_plugin_tools",
]
