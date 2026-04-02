# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Abstract extractor base class, unified ExtractionResult dataclass,
file-resolution helper, and the factory dispatcher ``extract_content``.
"""

import mimetypes
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import frappe

from idp.core.constants import EXTENSION_TO_MIME, SUPPORTED_MIME_TYPES
from idp.core.exceptions import ExtractionError, FileTooLargeError, UnsupportedFormatError
from idp.core.logger import get_logger

logger = get_logger("idp.extractors")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
	"""Unified extraction result across all formats."""

	content_type: str  # "text" | "tabular" | "image" | "mixed"
	text: str | None = None
	tables: list[list[list[str]]] | None = None  # list of tables, each = list of rows
	images: list[dict] | None = None  # base64 encoded images with metadata
	metadata: dict = field(default_factory=dict)  # file_name, mime_type, page_count …
	ocr_results: list | None = None  # raw OCRResult objects (images / scanned PDFs)
	confidence: float | None = None  # average OCR confidence 0.0-1.0


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseExtractor(ABC):
	"""Abstract base for all document extractors."""

	@abstractmethod
	def extract(self, file_path: str, **kwargs) -> ExtractionResult:
		"""Extract content from the given file."""

	@abstractmethod
	def supports_mime_type(self, mime_type: str) -> bool:
		"""Return ``True`` if this extractor handles *mime_type*."""


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------


def resolve_file(file_url: str) -> tuple[str, str]:
	"""Resolve a Frappe *file_url* to ``(absolute_path, mime_type)``.

	Handles ``/files/…`` and ``/private/files/…`` paths.  Verifies the
	file exists on disk and detects its MIME type.

	Raises:
		UnsupportedFormatError: MIME type is not in ``SUPPORTED_MIME_TYPES``.
		ExtractionError: File does not exist on disk.
		FileTooLargeError: File exceeds the configured size limit.
	"""
	# Resolve to absolute path via Frappe's site directory
	if file_url.startswith(("/files/", "/private/files/")):
		site_path = frappe.get_site_path()
		# /files/… lives under <site>/public/files/
		# /private/files/… lives under <site>/private/files/
		if file_url.startswith("/private/"):
			abs_path = os.path.join(site_path, file_url.lstrip("/"))
		else:
			abs_path = os.path.join(site_path, "public", file_url.lstrip("/"))
	elif os.path.isabs(file_url):
		abs_path = file_url
	else:
		# Attempt relative to site
		abs_path = os.path.join(frappe.get_site_path(), file_url.lstrip("/"))

	if not os.path.isfile(abs_path):
		raise ExtractionError(
			f"File not found on disk: {abs_path}",
			details={"file_url": file_url},
		)

	# Check file size
	from idp.core.constants import MAX_FILE_SIZE_BYTES

	file_size = os.path.getsize(abs_path)
	if file_size > MAX_FILE_SIZE_BYTES:
		from idp.core.constants import MAX_FILE_SIZE_MB

		raise FileTooLargeError(
			f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds limit ({MAX_FILE_SIZE_MB} MB)",
			details={"file_url": file_url, "size_bytes": file_size},
		)

	# Detect MIME type
	mime_type = _detect_mime_type(abs_path)
	if mime_type not in SUPPORTED_MIME_TYPES:
		raise UnsupportedFormatError(
			f"Unsupported file type: {mime_type}",
			details={"file_url": file_url, "mime_type": mime_type},
		)

	return abs_path, mime_type


def _detect_mime_type(file_path: str) -> str:
	"""Detect MIME type — extension-based with ``mimetypes`` fallback."""
	_, ext = os.path.splitext(file_path)
	ext = ext.lower()

	# Prefer our explicit mapping (avoids platform quirks)
	if ext in EXTENSION_TO_MIME:
		return EXTENSION_TO_MIME[ext]

	mime, _ = mimetypes.guess_type(file_path)
	return mime or "application/octet-stream"


# ---------------------------------------------------------------------------
# Factory dispatcher
# ---------------------------------------------------------------------------

# Registry populated on first call (avoids circular imports)
_extractors: list[BaseExtractor] | None = None


def _get_extractors() -> list[BaseExtractor]:
	"""Lazily build the extractor registry."""
	global _extractors
	if _extractors is None:
		from idp.idp.extractors.extractor import (
			CSVExtractor,
			DocxExtractor,
			ExcelExtractor,
			ImageExtractor,
			PDFExtractor,
		)

		_extractors = [
			PDFExtractor(),
			ImageExtractor(),
			ExcelExtractor(),
			CSVExtractor(),
			DocxExtractor(),
		]
	return _extractors


def extract_content(file_url: str, lang: str = "en") -> ExtractionResult:
	"""Factory function — resolve file, detect MIME type, dispatch to extractor.

	1. Resolve *file_url* to an absolute path (via Frappe File DocType).
	2. Detect MIME type.
	3. Dispatch to the first matching extractor.
	4. Return a unified :class:`ExtractionResult`.
	"""
	abs_path, mime_type = resolve_file(file_url)

	for extractor in _get_extractors():
		if extractor.supports_mime_type(mime_type):
			logger.info(
				f"Dispatching {mime_type} to {extractor.__class__.__name__} | file={file_url}"
			)
			return extractor.extract(abs_path, lang=lang, mime_type=mime_type, file_url=file_url)

	raise UnsupportedFormatError(
		f"No extractor found for MIME type: {mime_type}",
		details={"file_url": file_url, "mime_type": mime_type},
	)
