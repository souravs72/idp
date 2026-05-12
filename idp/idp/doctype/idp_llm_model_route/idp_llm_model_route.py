# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""IDP LLM Model Route — child of *IDP Settings*.

Each row maps a model *purpose* (classification, extraction, vision,
summarisation, confirmation) to a concrete (provider, model_name, tier).
Used by ``idp.llm.router.pick_model`` (Phase 16) to satisfy the
two-tier routing strategy described in roadmap v2 §TE.3.
"""

from frappe.model.document import Document


class IDPLLMModelRoute(Document):
	"""Controller for the *IDP LLM Model Route* child DocType."""

	pass
