# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Ollama vision OCR extractor (Phase 27 §27.2).

Used as a fallback when PaddleOCR is unavailable or fails on a given
image / PDF.  The configured Ollama provider's :meth:`vision_ocr` runs
a local LLaVA / minicpm-v model on each page; the recognised text is
returned in an :class:`ExtractionResult` with ``synthetic`` confidence.
"""

from __future__ import annotations

import os
import tempfile

from PIL import Image

from idp.core.config import (
	get_max_pdf_pages,
	get_vision_image_max_dim_px,
)
from idp.core.exceptions import ExtractionError, OCRError
from idp.core.logger import get_logger
from idp.extractors.base import BaseExtractor, ExtractionResult

logger = get_logger("idp.extractors.ollama_vision")


# MIME types this extractor will handle as a fallback.  PDFs are handled
# by rasterising each page to PNG first.
_SUPPORTED_IMAGE_MIMES = {
	"image/png",
	"image/jpeg",
	"image/webp",
	"image/tiff",
	"image/bmp",
}


class OllamaVisionExtractor(BaseExtractor):
	"""Run OCR via a local vision LLM hosted by Ollama."""

	def __init__(self, *, model: str | None = None) -> None:
		self.model = model

	# -- BaseExtractor API ---------------------------------------------------

	def supports_mime_type(self, mime_type: str) -> bool:
		if not mime_type:
			return False
		return mime_type == "application/pdf" or mime_type in _SUPPORTED_IMAGE_MIMES

	def extract(self, file_path: str, **kwargs) -> ExtractionResult:
		mime_type = kwargs.get("mime_type") or _guess_mime(file_path)
		provider = _get_ollama_provider()

		if mime_type == "application/pdf":
			pages = _pdf_to_image_pages(file_path)
		elif mime_type in _SUPPORTED_IMAGE_MIMES:
			pages = [(1, file_path)]
		else:
			raise ExtractionError(
				f"OllamaVisionExtractor cannot handle {mime_type!r}",
				details={"file_path": file_path},
			)

		max_dim = get_vision_image_max_dim_px()
		texts: list[str] = []
		page_confidences: list[float] = []
		temp_paths: list[str] = []
		try:
			for page_num, page_path in pages:
				prepared, created = _resize_for_vision(page_path, max_dim)
				if created:
					temp_paths.append(prepared)
				try:
					response = provider.vision_ocr(prepared, model=self.model)
				except Exception as exc:
					raise OCRError(
						f"Ollama vision OCR failed on page {page_num}: {exc}",
						details={"page": page_num, "file_path": file_path},
					) from exc

				body = (response.get("text") or "").strip()
				if body:
					texts.append(f"--- Page {page_num} ---\n{body}")
				page_confidences.append(float(response.get("confidence") or 0.0))
		finally:
			for path in temp_paths:
				_safe_remove(path)
			# Clean up rasterised PDF pages (those marked with .vision.png)
			for _page_num, path in pages:
				if path.endswith(".vision.png") and os.path.exists(path):
					_safe_remove(path)

		text = "\n\n".join(texts).strip()
		avg_conf = (
			sum(page_confidences) / len(page_confidences)
			if page_confidences
			else 0.0
		)

		return ExtractionResult(
			content_type="text",
			text=text,
			tables=None,
			metadata={
				"file_name": os.path.basename(file_path),
				"mime_type": mime_type,
				"page_count": len(pages),
				"extracted_pages": len(pages),
				"engine": "ollama_vision",
				"synthetic_confidence": True,
			},
			confidence=round(avg_conf, 4),
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ollama_provider():
	"""Resolve the configured Ollama provider instance.

	We deliberately bypass the ``LLMService`` here because this extractor
	must work even when the conversation's *primary* provider is
	OpenAI / Anthropic and Ollama is only the OCR fallback.
	"""

	from idp.core.config import get_idp_settings
	from idp.llm.providers.ollama_provider import OllamaProvider

	settings = get_idp_settings()
	host_url = (settings.get("ollama_host_url") or "http://localhost:11434").strip()
	return OllamaProvider(host_url=host_url)


def _guess_mime(file_path: str) -> str:
	import mimetypes

	mime, _ = mimetypes.guess_type(file_path)
	return mime or "application/octet-stream"


def _resize_for_vision(image_path: str, max_dim: int) -> tuple[str, bool]:
	"""Resize *image_path* if it exceeds *max_dim* on either axis.

	Returns ``(prepared_path, created_temp)``.  When the original image
	is already small enough we return its path with ``created_temp=False``
	so the caller knows not to delete it.
	"""

	try:
		img = Image.open(image_path)
	except Exception as exc:
		raise ExtractionError(
			f"Cannot open image for vision OCR: {exc}",
			details={"image_path": image_path},
		) from exc

	width, height = img.size
	if max(width, height) <= max_dim:
		return image_path, False

	scale = max_dim / float(max(width, height))
	new_size = (int(width * scale), int(height * scale))
	img = img.convert("RGB").resize(new_size, Image.LANCZOS)

	fd, tmp = tempfile.mkstemp(suffix=".vision.png")
	os.close(fd)
	img.save(tmp, format="PNG")
	return tmp, True


def _pdf_to_image_pages(file_path: str) -> list[tuple[int, str]]:
	"""Rasterise PDF pages into temporary PNGs for vision OCR."""

	max_pages = get_max_pdf_pages()
	try:
		from pdf2image import convert_from_path
	except ImportError as exc:
		raise ExtractionError(
			"pdf2image (poppler) is required to OCR PDFs via the vision fallback",
			details={"hint": "install poppler-utils + pdf2image"},
		) from exc

	images = convert_from_path(
		file_path,
		dpi=200,
		first_page=1,
		last_page=max_pages,
		fmt="png",
	)
	pages: list[tuple[int, str]] = []
	for idx, img in enumerate(images, start=1):
		fd, tmp = tempfile.mkstemp(suffix=".vision.png")
		os.close(fd)
		img.save(tmp, format="PNG")
		pages.append((idx, tmp))
	return pages


def _safe_remove(path: str) -> None:
	try:
		os.remove(path)
	except OSError:
		pass


__all__ = ["OllamaVisionExtractor"]
