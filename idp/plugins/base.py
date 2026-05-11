# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP plugin base class (Phase 26 §26.1).

A plugin bundles a set of tools (and optionally prompt templates /
skills) under a single namespace that can be toggled at runtime via
``IDP Plugin Configuration``.  Third-party Frappe apps can register
their own plugins by exposing a ``hooks.py`` entry::

    # In any installed app's hooks.py
    idp_plugins = "myapp.idp_integration:MyAppPlugin"

…or alternatively a tool-only hook::

    idp_tools = "myapp.idp_integration.get_tools"

The loader (``idp.plugins.loader``) discovers both forms and
wraps the tool-only hook in an anonymous plugin so the per-plugin
toggle still applies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from idp.idp.llm.tools.base import ToolSpec


@dataclass
class PluginTool:
    """Lightweight wrapper that ties a :class:`ToolSpec` to the
    declaring plugin.

    The plugin namespace flows through to ``IDP Tool Configuration``
    and the audit log so admins can filter by plugin.
    """

    plugin_name: str
    spec: ToolSpec


class IDPPlugin:
    """Abstract base class every IDP plugin implements.

    Concrete subclasses MUST define :attr:`name` and override
    :meth:`get_tools`.  The remaining attributes have sensible
    defaults so simple plugins can ship a single ``get_tools()``.

    Subclasses should be importable, side-effect-free at module load
    time, and idempotent — the loader caches plugin instances and may
    re-instantiate them on cache invalidation.
    """

    #: Unique slug, e.g. ``"core"`` or ``"acme_logistics"``.
    name: str = ""
    #: Human-readable label shown in the admin UI.
    display_name: str = ""
    #: SemVer string for diagnostics.
    version: str = "0.1.0"
    #: One-line summary surfaced in ``IDP Plugin Configuration``.
    description: str = ""
    #: When ``True`` the plugin is loaded but its tools are hidden
    #: unless an explicit ``IDP Plugin Configuration.enabled = 1``
    #: row exists.  Core plugins should keep this ``False``.
    optional: bool = False

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def get_tools(self) -> Iterable[ToolSpec]:
        """Return the tool specs this plugin contributes.

        The default implementation returns an empty iterable so a
        plugin can subclass purely to ship prompt templates / skills
        without any new tools.
        """

        return ()

    def is_available(self) -> bool:
        """Return ``False`` to disable the plugin without ever loading
        its tools (e.g. when an optional Python dependency is missing).

        The default returns ``True``.
        """

        return True

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "version": self.version,
            "description": self.description,
            "optional": bool(self.optional),
            "available": bool(self.is_available()),
        }


__all__ = ["IDPPlugin", "PluginTool"]
