# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Custom exception hierarchy for the IDP module.

All IDP-specific exceptions inherit from ``IDPError`` so callers can
catch the entire family with a single ``except IDPError`` clause.
"""


class IDPError(Exception):
	"""Base exception for all IDP errors."""

	def __init__(self, message: str = "", *, details: dict | None = None):
		self.details = details or {}
		super().__init__(message)


class ExtractionError(IDPError):
	"""Error during document content extraction."""


class OCRError(IDPError):
	"""PaddleOCR processing error."""


class ValidationError(IDPError):
	"""Extracted data fails schema or business validation."""


class MappingError(IDPError):
	"""Cannot map extracted data to ERPNext DocType."""


class UnsupportedFormatError(IDPError):
	"""File format not supported for extraction."""


class FileTooLargeError(IDPError):
	"""File exceeds maximum allowed size."""


class MissingMasterError(IDPError):
	"""Required master records (Supplier, Customer, Item) not found."""


class RateLimitExceededError(IDPError):
	"""Caller exceeded per-user or global extraction rate limit (Phase 14)."""


class SecurityError(IDPError):
	"""Request violated a security guard (bad MIME, path traversal, permission
	denied) enforced by :mod:`idp.core.security` (Phase 14)."""


class LLMError(IDPError):
	"""Base class for LLM-provider related failures (Phase 16)."""


class LLMBudgetExceededError(LLMError):
	"""Caller exceeded daily or monthly token budget configured in IDP Settings."""


class LLMProviderUnavailableError(LLMError):
	"""Requested provider is not registered, or its SDK/host is unavailable."""


class LLMResponseParseError(LLMError):
	"""Could not parse the provider's response into an :class:`LLMResponse`."""


class FileAliasNotFoundError(IDPError):
	"""LLM supplied an unknown file alias (Phase 18).

	Always raised with ``stop_processing=True`` semantics so the tool
	loop halts instead of speculatively retrying with a different alias
	the LLM might invent.
	"""

	def __init__(self, alias: str, *, conversation_id: str | None = None):
		self.alias = alias
		self.conversation_id = conversation_id
		details: dict = {"alias": alias, "stop_processing": True}
		if conversation_id:
			details["conversation_id"] = conversation_id
		super().__init__(f"unknown file alias: {alias!r}", details=details)
