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
