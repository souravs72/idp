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


class ConfirmationCardError(IDPError):
	"""ConfirmationCard validation or commit failure (Phase 20).

	Raised by :func:`idp.api.conversation.confirm_card` when the
	payload is malformed, the action is not in the card's allowed
	list, or the user-edited values fail re-validation.
	"""


# ---------------------------------------------------------------------------
# Phase 27 — Extraction hardening
# ---------------------------------------------------------------------------


class IDPPermissionError(SecurityError):
	"""User lacks permission to access a file or its attached parent
	DocType (Phase 27 §27.3).

	Raised as a subclass of :class:`SecurityError` so existing
	permission-handling code keeps working, but with a more specific
	type for the file-level case.  Always raised with the
	``PARENT_DOCTYPE_FORBIDDEN`` or ``FILE_FORBIDDEN`` error code in
	``details`` so the Phase 23 envelope mapper can show a friendly
	card.
	"""

	def __init__(
		self,
		message: str = "",
		*,
		code: str = "FILE_FORBIDDEN",
		details: dict | None = None,
	):
		merged: dict = {"error_code": code}
		if details:
			merged.update(details)
		super().__init__(message, details=merged)
		self.code = code


class OCRTimeoutError(OCRError):
	"""PaddleOCR subprocess exceeded the configured timeout (Phase 27 §27.1)."""

	def __init__(self, message: str = "OCR processing timed out", *, timeout_seconds: float | None = None):
		details: dict = {"error_code": "OCR_TIMEOUT"}
		if timeout_seconds is not None:
			details["timeout_seconds"] = timeout_seconds
		super().__init__(message, details=details)


class InsufficientMemoryError(OCRError):
	"""Pre-flight check found insufficient available memory for OCR
	(Phase 27 §27.1)."""

	def __init__(
		self,
		message: str = "Insufficient memory for OCR processing",
		*,
		available_mb: float | None = None,
		required_mb: float | None = None,
	):
		details: dict = {"error_code": "INSUFFICIENT_MEMORY"}
		if available_mb is not None:
			details["available_mb"] = available_mb
		if required_mb is not None:
			details["required_mb"] = required_mb
		super().__init__(message, details=details)


class PDFTooManyPagesError(ExtractionError):
	"""PDF page count exceeds the configured cap (Phase 27 §27.5)."""

	def __init__(self, message: str = "PDF has too many pages", *, pages: int | None = None, max_pages: int | None = None):
		details: dict = {"error_code": "PDF_TOO_MANY_PAGES"}
		if pages is not None:
			details["pages"] = pages
		if max_pages is not None:
			details["max_pages"] = max_pages
		super().__init__(message, details=details)
