# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Built-in *core* plugin (Phase 26 §26.1).

Wraps the existing in-tree tool set (``extract_document``,
``create_document``, …) under a single plugin namespace so admins can
treat it uniformly with third-party plugins in
``IDP Plugin Configuration``.  Disabling the core plugin effectively
turns the agent loop into a no-op — useful for emergency lockdowns.
"""

from __future__ import annotations

from collections.abc import Iterable

from idp.tools.base import ToolSpec
from idp.plugins.base import IDPPlugin


class CorePlugin(IDPPlugin):
    """Default plugin that exposes every tool registered via the
    in-tree ``@tool`` decorator.

    The list is sourced lazily from the registry so new tools added
    by future phases are picked up automatically.
    """

    name = "core"
    display_name = "IDP Core"
    version = "1.0.0"
    description = (
        "Built-in extraction / mapping / creation tool set shipped with the "
        "IDP app.  Disable only for emergency lockdowns."
    )
    optional = False

    def get_tools(self) -> Iterable[ToolSpec]:
        # Local import to avoid a circular dependency at module load
        # time (the registry imports the tool modules which would in
        # turn import this file if it were top-level).
        from idp.tools.registry import list_tools

        return list(list_tools())

    def is_available(self) -> bool:
        return True


__all__ = ["CorePlugin"]
