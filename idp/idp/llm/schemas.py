# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""JSON-Schema definitions for LLM tool calls.

Tool schemas use the OpenAI-style envelope; the Anthropic adapter
translates to Anthropic's ``input_schema`` format at call time.
"""

from __future__ import annotations

FIELD_MAPPING_TOOL_SCHEMA: dict = {
	"type": "function",
	"function": {
		"name": "map_document_fields",
		"description": (
			"Map extracted document text into an ERPNext DocType schema. "
			"Return a structured mapping with per-field confidence scores so "
			"the hybrid mapper can decide which LLM values to accept over "
			"rule-based values."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"header": {
					"type": "object",
					"description": "Header-level fieldname → value mapping",
					"additionalProperties": {"type": ["string", "number", "boolean", "null"]},
				},
				"items": {
					"type": "array",
					"description": "Child-table rows (empty list when the DocType has no line items)",
					"items": {
						"type": "object",
						"additionalProperties": {"type": ["string", "number", "boolean", "null"]},
					},
				},
				"confidence_scores": {
					"type": "object",
					"description": "Per-fieldname confidence in [0, 1]",
					"additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
				},
				"warnings": {
					"type": "array",
					"description": "Human-readable warnings for the operator",
					"items": {"type": "string"},
				},
			},
			"required": ["header"],
			"additionalProperties": False,
		},
	},
}


CLARIFICATION_TOOL_SCHEMA: dict = {
	"type": "function",
	"function": {
		"name": "request_clarification",
		"description": (
			"Ask the user a targeted question when the document is ambiguous. "
			"Used by the Phase 18 conversational assistant; exposed here so "
			"providers can advertise the same tool catalogue everywhere."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"question": {"type": "string"},
				"fieldname": {"type": "string"},
				"candidates": {"type": "array", "items": {"type": "string"}},
			},
			"required": ["question"],
			"additionalProperties": False,
		},
	},
}


# Phase 20 — ConfirmationCard payload schema version.  Bump whenever the
# card payload shape changes so the UI can refuse to render outdated
# (or future) payloads, and so server-side ``confirm_card`` can validate
# the version round-tripped from the client.
CONFIRMATION_CARD_PAYLOAD_VERSION: int = 1


__all__ = [
	"CLARIFICATION_TOOL_SCHEMA",
	"CONFIRMATION_CARD_PAYLOAD_VERSION",
	"FIELD_MAPPING_TOOL_SCHEMA",
]
