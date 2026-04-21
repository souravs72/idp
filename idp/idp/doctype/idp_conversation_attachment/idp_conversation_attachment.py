# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP Conversation Attachment — child table of IDP Conversation.

Holds one row per uploaded file plus the monotonic ``file_id`` alias
used by the LLM tool-calling loop.  See Phase 18 of the roadmap for the
alias system.
"""

from frappe.model.document import Document


class IDPConversationAttachment(Document):
	"""Child table row — no custom logic beyond the schema."""

	pass
