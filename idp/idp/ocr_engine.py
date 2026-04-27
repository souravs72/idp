# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""PaddleOCR wrapper for document extraction.

Provides a singleton OCR engine, image preprocessing, text / table /
layout extraction, and multi-page PDF processing.  All public functions
return structured dataclasses defined in this module.

PaddleOCR models are loaded once and reused across requests (singleton
via module-level reference, thread-safe under the GIL).
"""

import os
import tempfile
import time
from dataclasses import dataclass, field

from PIL import Image, ImageEnhance, ImageFilter

from idp.core.constants import MAX_PAGES_PER_PDF
from idp.core.exceptions import OCRError
from idp.core.logger import get_logger, log_ocr_result

logger = get_logger("idp.ocr")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TextBlock:
	"""A single recognised text region."""

	text: str
	confidence: float
	bbox: list[list[float]]  # 4-point bounding box
	block_type: str = "body"  # "title", "body", "footer", etc.


@dataclass
class Table:
	"""A table extracted from a document page."""

	rows: list[list[str]]
	bbox: list[list[float]] = field(default_factory=list)
	confidence: float = 0.0


@dataclass
class LayoutRegion:
	"""A single layout region detected on a page."""

	region_type: str  # "title", "text", "table", "figure"
	bbox: list[list[float]]
	content: str = ""


@dataclass
class LayoutAnalysis:
	"""Full layout analysis for a page."""

	regions: list[LayoutRegion] = field(default_factory=list)


@dataclass
class OCRResult:
	"""Structured OCR result for a single page."""

	page_number: int
	text_blocks: list[TextBlock] = field(default_factory=list)
	tables: list[Table] = field(default_factory=list)
	layout: LayoutAnalysis = field(default_factory=LayoutAnalysis)
	average_confidence: float = 0.0
	language: str = "en"
	processing_time_ms: int = 0


# ---------------------------------------------------------------------------
# Singleton engine cache  (one instance per language)
# ---------------------------------------------------------------------------
_ocr_engines: dict[str, object] = {}
_structure_engines: dict[str, object] = {}


def get_ocr_engine(lang: str = "en"):
	"""Get or create a PaddleOCR instance for *lang*.

	Models are loaded on first call and reused for subsequent requests.
	Thread-safe under CPython's GIL.
	"""
	global _ocr_engines
	if lang not in _ocr_engines:
		try:
			from paddleocr import PaddleOCR
		except ImportError:
			raise OCRError(
				"PaddleOCR is not installed. Install with: pip install paddleocr",
				details={"lang": lang},
			)

		try:
			_ocr_engines[lang] = PaddleOCR(
				use_angle_cls=True,
				lang=lang,
				show_log=False,
			)
		except Exception as exc:
			raise OCRError(
				f"Failed to initialise PaddleOCR for language '{lang}': {exc}",
				details={"lang": lang},
			)

	return _ocr_engines[lang]


def get_structure_engine(lang: str = "en"):
	"""Get or create a PPStructure instance for table / layout extraction."""
	global _structure_engines
	if lang not in _structure_engines:
		try:
			from paddleocr import PPStructure
		except ImportError:
			raise OCRError(
				"PaddleOCR (PPStructure) is not installed. Install with: pip install paddleocr",
				details={"lang": lang},
			)

		try:
			_structure_engines[lang] = PPStructure(
				lang=lang,
				show_log=False,
			)
		except Exception as exc:
			raise OCRError(
				f"Failed to initialise PPStructure for language '{lang}': {exc}",
				details={"lang": lang},
			)

	return _structure_engines[lang]


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


def preprocess_image(image_path: str) -> str:
	"""Apply preprocessing to improve OCR accuracy.

	Steps:
	1. Convert to grayscale
	2. Enhance contrast for faded documents
	3. Apply light sharpening
	4. Resize if too small (< 300 DPI equivalent, i.e. width < 1500px)

	Returns:
		Path to the preprocessed image (a temporary file the caller
		should delete when finished).
	"""
	try:
		img = Image.open(image_path)
	except Exception as exc:
		raise OCRError(f"Cannot open image '{image_path}': {exc}")

	# 1. Grayscale
	if img.mode != "L":
		img = img.convert("L")

	# 2. Contrast enhancement (1.5x boost)
	enhancer = ImageEnhance.Contrast(img)
	img = enhancer.enhance(1.5)

	# 3. Light sharpen
	img = img.filter(ImageFilter.SHARPEN)

	# 4. Upscale small images (width < 1500px ≈ 5" at 300 DPI)
	min_width = 1500
	if img.width < min_width:
		scale = min_width / img.width
		new_size = (int(img.width * scale), int(img.height * scale))
		img = img.resize(new_size, Image.LANCZOS)

	# Write to temp file
	fd, tmp_path = tempfile.mkstemp(suffix=".png")
	os.close(fd)
	img.save(tmp_path, format="PNG")
	return tmp_path


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text(file_path: str, lang: str = "en") -> list[dict]:
	"""Extract text with bounding boxes from an image or PDF page.

	Returns:
		List of dicts, each with keys ``text``, ``confidence``, ``bbox``.
		``bbox`` is a list of four ``[x, y]`` corner points.
	"""
	engine = get_ocr_engine(lang)
	try:
		result = engine.ocr(file_path, cls=True)
	except Exception as exc:
		raise OCRError(f"OCR text extraction failed for '{file_path}': {exc}")

	blocks: list[dict] = []
	if not result:
		return blocks

	# PaddleOCR returns a list of pages; each page is a list of line results.
	for page in result:
		if not page:
			continue
		for line in page:
			bbox, (text, confidence) = line
			blocks.append(
				{
					"text": text,
					"confidence": float(confidence),
					"bbox": bbox,
				}
			)

	return blocks


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


def extract_table(file_path: str, lang: str = "en") -> list[Table]:
	"""Extract table structures from an image via PPStructure.

	Returns:
		A list of :class:`Table` objects.
	"""
	engine = get_structure_engine(lang)
	try:
		result = engine(file_path)
	except Exception as exc:
		raise OCRError(f"Table extraction failed for '{file_path}': {exc}")

	tables: list[Table] = []
	if not result:
		return tables

	for region in result:
		if region.get("type") != "table":
			continue

		res = region.get("res")
		if not res:
			continue

		# PPStructure returns an HTML table string in res["html"]
		# and cell results in res (list of dicts with text + bbox).
		# We normalise into row/cell lists.
		rows = _parse_structure_table(res)
		bbox = region.get("bbox", [])
		tables.append(Table(rows=rows, bbox=bbox))

	return tables


def _parse_structure_table(res) -> list[list[str]]:
	"""Convert PPStructure table result into a list of rows."""
	# res may be a dict with "html" key, or a list of cell dicts.
	if isinstance(res, dict) and "html" in res:
		return _html_table_to_rows(res["html"])

	# Fallback: treat res as a list of detected text blocks, one per cell.
	if isinstance(res, list):
		return [[entry.get("text", "") for entry in res if isinstance(entry, dict)]]

	return []


def _html_table_to_rows(html: str) -> list[list[str]]:
	"""Naively parse an HTML ``<table>`` into a list of row-lists.

	This avoids pulling in a full HTML parser for the simple tables that
	PPStructure produces (``<tr><td>…</td></tr>``).
	"""
	import re

	rows: list[list[str]] = []
	# Split on <tr> … </tr>
	tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
	td_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
	tag_strip = re.compile(r"<[^>]+>")

	for tr_match in tr_pattern.finditer(html):
		cells: list[str] = []
		for td_match in td_pattern.finditer(tr_match.group(1)):
			cell_text = tag_strip.sub("", td_match.group(1)).strip()
			cells.append(cell_text)
		if cells:
			rows.append(cells)

	return rows


# ---------------------------------------------------------------------------
# Layout analysis
# ---------------------------------------------------------------------------


def extract_layout(file_path: str, lang: str = "en") -> LayoutAnalysis:
	"""Analyse document layout -- headers, paragraphs, tables, figures.

	Returns a :class:`LayoutAnalysis` with detected regions.
	"""
	engine = get_structure_engine(lang)
	try:
		result = engine(file_path)
	except Exception as exc:
		raise OCRError(f"Layout analysis failed for '{file_path}': {exc}")

	regions: list[LayoutRegion] = []
	if not result:
		return LayoutAnalysis(regions=regions)

	for region in result:
		region_type = region.get("type", "text")
		bbox = region.get("bbox", [])

		# Extract textual content from the region
		content = ""
		res = region.get("res")
		if isinstance(res, list):
			content = " ".join(entry.get("text", "") for entry in res if isinstance(entry, dict))
		elif isinstance(res, dict):
			content = res.get("text", "")

		regions.append(LayoutRegion(region_type=region_type, bbox=bbox, content=content))

	return LayoutAnalysis(regions=regions)


# ---------------------------------------------------------------------------
# Multi-page PDF processing
# ---------------------------------------------------------------------------


def process_pdf(
	file_path: str,
	lang: str = "en",
	max_pages: int = MAX_PAGES_PER_PDF,
) -> list[OCRResult]:
	"""Process each page of a PDF through PaddleOCR.

	For each page the function:
	1. Converts the PDF page to an image (via ``pypdf`` + Pillow rendering,
	   falling back to ``pdf2image`` if available).
	2. Preprocesses the image.
	3. Runs OCR text extraction.
	4. Runs table extraction.
	5. Runs layout analysis.
	6. Aggregates results into an :class:`OCRResult` per page.

	Args:
		file_path: Path to the PDF file.
		lang: PaddleOCR language code.
		max_pages: Maximum number of pages to process.

	Returns:
		A list of :class:`OCRResult`, one per processed page.
	"""
	page_images = _pdf_to_images(file_path, max_pages=max_pages)
	results: list[OCRResult] = []

	for page_num, page_img_path in enumerate(page_images, start=1):
		preprocessed_path: str | None = None
		try:
			start = time.perf_counter_ns()

			# Preprocess
			preprocessed_path = preprocess_image(page_img_path)

			# Extract
			text_dicts = extract_text(preprocessed_path, lang=lang)
			tables = extract_table(preprocessed_path, lang=lang)
			layout = extract_layout(preprocessed_path, lang=lang)

			elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000

			# Build TextBlock list
			text_blocks = [
				TextBlock(
					text=d["text"],
					confidence=d["confidence"],
					bbox=d["bbox"],
				)
				for d in text_dicts
			]

			# Compute average confidence
			avg_conf = 0.0
			if text_blocks:
				avg_conf = sum(b.confidence for b in text_blocks) / len(text_blocks)

			results.append(
				OCRResult(
					page_number=page_num,
					text_blocks=text_blocks,
					tables=tables,
					layout=layout,
					average_confidence=round(avg_conf, 4),
					language=lang,
					processing_time_ms=elapsed_ms,
				)
			)

		except OCRError:
			raise
		except Exception as exc:
			logger.warning(f"OCR failed on page {page_num} of '{file_path}': {exc}")
			results.append(OCRResult(page_number=page_num, language=lang))
		finally:
			# Clean up temp files
			_safe_remove(page_img_path)
			if preprocessed_path:
				_safe_remove(preprocessed_path)

	# Log aggregate result
	if results:
		total_conf = [r.average_confidence for r in results if r.text_blocks]
		avg = sum(total_conf) / len(total_conf) if total_conf else 0.0
		log_ocr_result(
			file_url=file_path,
			pages=len(results),
			avg_confidence=round(avg, 4),
			language=lang,
		)

	return results


# ---------------------------------------------------------------------------
# PDF to images helper
# ---------------------------------------------------------------------------


def _pdf_to_images(file_path: str, max_pages: int = MAX_PAGES_PER_PDF) -> list[str]:
	"""Convert PDF pages to temporary PNG images.

	Tries ``pdf2image`` (poppler) first for best quality, then falls
	back to ``pypdf`` page-by-page rendering.

	Returns:
		List of temporary file paths (PNG), one per page.
	"""
	paths: list[str] = []

	# Strategy 1: pdf2image (requires poppler)
	try:
		from pdf2image import convert_from_path

		images = convert_from_path(
			file_path,
			dpi=300,
			first_page=1,
			last_page=max_pages,
			fmt="png",
		)
		for img in images:
			fd, tmp = tempfile.mkstemp(suffix=".png")
			os.close(fd)
			img.save(tmp, format="PNG")
			paths.append(tmp)
		return paths
	except ImportError:
		pass
	except Exception as exc:
		logger.warning(f"pdf2image failed, falling back to pypdf: {exc}")

	# Strategy 2: pypdf page extraction → re-render via PaddleOCR directly
	# PaddleOCR can accept a PDF path and process pages itself. We split
	# the PDF into single-page PDFs so we can preprocess each individually.
	try:
		from pypdf import PdfReader, PdfWriter

		reader = PdfReader(file_path)
		page_count = min(len(reader.pages), max_pages)

		for i in range(page_count):
			writer = PdfWriter()
			writer.add_page(reader.pages[i])
			fd, tmp = tempfile.mkstemp(suffix=".pdf")
			os.close(fd)
			with open(tmp, "wb") as f:
				writer.write(f)
			paths.append(tmp)

		return paths
	except Exception as exc:
		raise OCRError(
			f"Failed to split PDF into pages: {exc}",
			details={"file_path": file_path},
		)


# ---------------------------------------------------------------------------
# Phase 22 — Language auto-detection
# ---------------------------------------------------------------------------


# Unicode block fingerprints used to fall back to script-based detection
# when no LLM/PaddleOCR detector is available.  Only languages supported
# by PaddleOCR are listed; everything else returns ``"en"``.
_SCRIPT_FINGERPRINTS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
	# Devanagari → Hindi
	("hi", (("\u0900", "\u097f"),)),
	# Arabic → Arabic
	("ar", (("\u0600", "\u06ff"), ("\u0750", "\u077f"))),
	# CJK Unified Ideographs → Chinese (default for unspecified Han text)
	("ch", (("\u4e00", "\u9fff"), ("\u3400", "\u4dbf"))),
	# Hiragana / Katakana → Japanese
	("ja", (("\u3040", "\u309f"), ("\u30a0", "\u30ff"))),
	# Hangul → Korean
	("ko", (("\uac00", "\ud7af"), ("\u1100", "\u11ff"))),
	# Tamil
	("ta", (("\u0b80", "\u0bff"),)),
	# Telugu
	("te", (("\u0c00", "\u0c7f"),)),
)


def detect_language(file_path: str, *, sample_chars: int = 4_000) -> str:
	"""Best-effort language detection for an image / PDF.

	Strategy (cheapest first):

	1. Run a quick OCR pass with the multi-language ``ml`` PaddleOCR
	   model — this is what PaddleOCR ships specifically for language
	   identification.  When that's unavailable we fall back to step 2.
	2. Run a small English OCR pass on the first page just to lift
	   *some* text, then inspect the Unicode blocks present.  Anything
	   that's mostly Latin is treated as English; otherwise the most
	   prevalent script wins.
	3. On any failure we return ``"en"`` — never raise — so the caller
	   can always proceed with a default model.

	The function is deliberately silent about latin-script languages
	(``en``/``fr``/``de``/``es``/``pt``):  PaddleOCR's character coverage
	is identical for them and the script-based heuristic can't tell
	them apart.  Sites that need that distinction should set
	``ocr_language`` explicitly on the conversation.
	"""

	if not file_path:
		return "en"

	# Strategy 1 — PaddleOCR multi-language detector.  We import lazily
	# and tolerate any failure, since the "ml" lang isn't always
	# downloaded on a fresh install.
	try:
		from paddleocr import PaddleOCR

		detector = PaddleOCR(use_angle_cls=False, lang="ml", show_log=False)
		try:
			result = detector.ocr(file_path, cls=False)
		except Exception:
			result = None
		if result:
			text = _flatten_ocr_text(result, limit=sample_chars)
			if text:
				return _language_from_unicode(text)
	except Exception as exc:
		logger.debug(f"detect_language: PaddleOCR ml model unavailable ({exc})")

	# Strategy 2 — English-model OCR pass + script analysis.  Even on a
	# Hindi document the English model picks up enough Devanagari
	# characters for the script heuristic to fire.
	try:
		text = " ".join(b.get("text", "") for b in extract_text(file_path, lang="en"))
		text = text[:sample_chars]
	except Exception as exc:
		logger.debug(f"detect_language: english pass failed ({exc})")
		return "en"

	if not text.strip():
		return "en"
	return _language_from_unicode(text)


def _flatten_ocr_text(result, *, limit: int) -> str:
	"""Collapse a PaddleOCR result tree into a single string."""

	chunks: list[str] = []
	total = 0
	for page in result or []:
		for line in page or []:
			try:
				_bbox, (text, _conf) = line
			except (TypeError, ValueError):
				continue
			if not text:
				continue
			chunks.append(str(text))
			total += len(text)
			if total >= limit:
				return " ".join(chunks)
	return " ".join(chunks)


def _language_from_unicode(text: str) -> str:
	"""Pick the best language code by counting characters per script."""

	scores: dict[str, int] = {}
	for ch in text:
		for lang, ranges in _SCRIPT_FINGERPRINTS:
			for lo, hi in ranges:
				if lo <= ch <= hi:
					scores[lang] = scores.get(lang, 0) + 1
					break
	if not scores:
		return "en"
	# Pick the script with the most hits.  Ties broken by registration
	# order in ``_SCRIPT_FINGERPRINTS`` to keep behaviour stable.
	best_lang, _best_count = max(scores.items(), key=lambda kv: kv[1])
	return best_lang


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _safe_remove(path: str) -> None:
	"""Remove a file, ignoring errors if it doesn't exist."""
	try:
		os.remove(path)
	except OSError:
		pass
