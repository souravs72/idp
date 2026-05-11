# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Built-in tool registrations for the IDP agent loop (Phase 19).

Importing this package triggers each module's ``@tool`` decorator,
populating :mod:`idp.llm.tools.registry`.  Callers should:

    from idp.llm.tools.registry import (
        load_tool_registry,
        get_provider_schemas,
        dispatch,
    )

and let ``load_tool_registry()`` do the side-effect imports — it
calls back into this package.
"""

# Side-effect imports — each module registers a ToolSpec with the
# global registry.  Order is irrelevant; we list alphabetically.
from idp.llm.tools import (
	ask_user,
	compare_document,
	create_document,
	create_master,
	extract_document,
	find_matching_record,
	list_missing_masters,
	propose_create_document,
	read_attachment_more,
	validate_document,
)
from idp.llm.tools.base import ToolContext, ToolResult, ToolSpec, tool

__all__ = [
	"ToolContext",
	"ToolResult",
	"ToolSpec",
	"tool",
]
