# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Tool Configuration controller (Phase 26 §26.2).

Stores per-tool admin overrides: enabled flag, allowed / denied role
table, confirmation requirement.  ``ToolRegistry.dispatch`` consults
this DocType — when no row exists the in-code ``ToolSpec`` defaults
apply, so the feature is fully non-breaking.

Writes invalidate the tool-registry cache.
"""

from __future__ import annotations

from frappe.model.document import Document


class IDPToolConfiguration(Document):
    """Controller for the *IDP Tool Configuration* DocType."""

    def on_update(self) -> None:  # noqa: D401
        self._invalidate_caches()

    def on_trash(self) -> None:  # noqa: D401
        self._invalidate_caches()

    def _invalidate_caches(self) -> None:
        try:
            from idp.idp.llm.tools.access import invalidate_tool_config_cache

            invalidate_tool_config_cache(self.tool_name)
        except Exception:
            pass
        try:
            from idp.idp.llm.tools.registry_cache import invalidate_tool_registry_cache

            invalidate_tool_registry_cache()
        except Exception:
            pass
        try:
            from idp.plugins.loader import invalidate_plugin_cache

            invalidate_plugin_cache()
        except Exception:
            pass
