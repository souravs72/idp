# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP plugin subsystem (Phase 26).

Native plugin architecture for IDP.  See
:mod:`idp.plugins.base` for the contract and
:mod:`idp.plugins.core_plugin` for the built-in implementation
that wraps the existing tool registry.

Public surface::

    from idp.plugins import (
        IDPPlugin,
        discover_plugins,
        enabled_plugins,
        invalidate_plugin_cache,
    )
"""

from idp.plugins.base import IDPPlugin, PluginTool
from idp.plugins.loader import (
    discover_plugins,
    enabled_plugins,
    invalidate_plugin_cache,
    register_plugin_tools,
)

__all__ = [
    "IDPPlugin",
    "PluginTool",
    "discover_plugins",
    "enabled_plugins",
    "invalidate_plugin_cache",
    "register_plugin_tools",
]
