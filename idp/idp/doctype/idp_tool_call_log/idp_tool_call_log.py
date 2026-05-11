# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Tool Call Log controller (Phase 26 §26.5).

Audit log row created by :func:`idp.llm.tools.audit.log_tool_call`
after every dispatch.  Sized to fit ~2 KB result excerpts so the
table stays scannable; the full payload remains on the originating
``IDP Message`` row.
"""

from frappe.model.document import Document


class IDPToolCallLog(Document):
    """Controller for the *IDP Tool Call Log* DocType."""

    pass
