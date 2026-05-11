# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Skill controller (Phase 26 §26.6).

Markdown extraction rules + examples appended to the system prompt
for matching conversations.  Writes invalidate the lookup cache.
"""

from __future__ import annotations

from frappe.model.document import Document


class IDPSkill(Document):
    """Controller for the *IDP Skill* DocType."""

    def on_update(self) -> None:  # noqa: D401
        self._invalidate_cache()

    def on_trash(self) -> None:  # noqa: D401
        self._invalidate_cache()

    @staticmethod
    def _invalidate_cache() -> None:
        try:
            from idp.llm.skills import invalidate_skills_cache

            invalidate_skills_cache()
        except Exception:
            pass
