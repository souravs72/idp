# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Built-in tool registrations for the IDP agent loop (Phase 19).

Importing this package triggers each module's ``@tool`` decorator,
populating :mod:`idp.tools.registry`.  Callers should:

    from idp.tools.registry import (
        load_tool_registry,
        get_provider_schemas,
        dispatch,
    )

and let ``load_tool_registry()`` do the side-effect imports — it
calls back into this package.

LLM-exposed tools (10):
    ask_user, compare_document, create_document, delete_document,
    extract_document, propose_create_document, resolve_masters,
    search_documents, update_document, validate_document

Retired (now shims, not LLM-exposed):
    create_master, find_matching_record, list_missing_masters,
    read_attachment_more
"""

# Side-effect imports — each module registers a ToolSpec with the
# global registry.  Order is irrelevant; we list alphabetically.
from idp.tools import (
	ask_user,
	compare_document,
	create_document,
	delete_document,
	extract_document,
	propose_create_document,
	resolve_masters,
	search_documents,
	update_document,
	validate_document,
)
from idp.tools.base import ToolContext, ToolResult, ToolSpec, tool

__all__ = [
	"ToolContext",
	"ToolResult",
	"ToolSpec",
	"tool",
]
