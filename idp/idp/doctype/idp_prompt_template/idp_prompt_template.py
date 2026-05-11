# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Prompt Template controller (Phase 26 §26.4).

* Validates Jinja syntax on save (compile-only — no render).
* Invalidates the prompt-template lookup cache.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class IDPPromptTemplate(Document):
    """Controller for the *IDP Prompt Template* DocType."""

    def validate(self) -> None:  # noqa: D401
        self._validate_jinja_syntax()

    def on_update(self) -> None:  # noqa: D401
        self._invalidate_cache()

    def on_trash(self) -> None:  # noqa: D401
        self._invalidate_cache()

    # ------------------------------------------------------------------

    def _validate_jinja_syntax(self) -> None:
        if not self.system_prompt:
            return
        try:
            from jinja2 import Environment, TemplateSyntaxError

            Environment().parse(self.system_prompt)
        except TemplateSyntaxError as exc:
            frappe.throw(
                _("Invalid Jinja syntax in system prompt: {0}").format(str(exc)),
                title=_("Prompt Template Error"),
            )
        except ImportError:
            # Jinja2 is a Frappe dep — should never happen at runtime,
            # but skip silently in pure-Python test environments.
            return

    @staticmethod
    def _invalidate_cache() -> None:
        try:
            from idp.llm.prompt_templates import invalidate_template_cache

            invalidate_template_cache()
        except Exception:
            pass
