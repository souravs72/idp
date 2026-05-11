# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Plugin Configuration controller (Phase 26 §26.1).

Writes/deletes invalidate the plugin discovery + tool-registry caches
so admin changes propagate without a worker restart.
"""

from __future__ import annotations

from frappe.model.document import Document


class IDPPluginConfiguration(Document):
    """Controller for the *IDP Plugin Configuration* DocType."""

    def on_update(self) -> None:  # noqa: D401
        self._invalidate_caches()

    def on_trash(self) -> None:  # noqa: D401
        self._invalidate_caches()

    @staticmethod
    def _invalidate_caches() -> None:
        try:
            from idp.plugins.loader import invalidate_plugin_cache

            invalidate_plugin_cache()
        except Exception:
            # Cache invalidation is best-effort — never block a save.
            pass
