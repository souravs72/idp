# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Read a scanned page with the OpenAI or Anthropic model in IDP Settings.

Callers: PDFExtractor.extract, ImageExtractor.extract, and extract_content
when a local engine fails. No new API schema. The user said: simplify the
IDP app so it requires only necessary installs, use an Anthropic or OpenAI
API key, and install those dependencies with the Frappe app.
"""

from __future__ import annotations

import base64
import os
import tempfile

_PROMPT = (
	"Transcribe this invoice in plain text. No markdown, asterisks, or commentary. "
	"Put the seller name on its own line, then a line that says TAX INVOICE. "
	"Put the seller tax number on its own line as TRN followed by its digits, with no spaces. "
	"A UAE TRN is 15 digits. Copy it exactly. "
	"Put the invoice number, invoice date, and due date on their own lines. "
	"Put each total on its own line as the label, a space, then the amount with a decimal point and no thousands comma. "
	"Put each item on one line: index, item code, description, quantity, unit, rate, taxable amount, VAT, total. "
	"Do not invent figures."
)
_MAX_PAGES = 3
_LONG_EDGE = 2048


def read_pages(file_path: str) -> str:
	"""Transcribe a PDF or image. Raises when no cloud model is configured."""
	from idp.core.exceptions import ExtractionError

	client = _vision_client()
	if client is None:
		raise ExtractionError(
			"Save an OpenAI or Anthropic API key in IDP Settings. "
			"A scanned page is read by that model."
		)

	pages = _page_images(file_path)
	if not pages:
		raise ExtractionError("The page could not be rendered for reading.")

	parts: list[str] = []
	try:
		for number, image in pages:
			text = _read_page(client, image).strip()
			if text:
				parts.append(f"--- Page {number} ---\n{text}")
	finally:
		_cleanup(file_path, pages)
	body = "\n\n".join(parts).strip()
	if not body:
		raise ExtractionError("The model returned no text for this page.")
	return body


def image_content(provider, image_path: str, prompt: str) -> list[dict]:
	"""Image block in the shape the provider's chat API accepts."""
	mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
	encoded = base64.b64encode(_read_bytes(image_path)).decode("ascii")
	if provider.__class__.__name__ == "AnthropicProvider":
		return [
			{"type": "image", "source": {"type": "base64", "media_type": mime, "data": encoded}},
			{"type": "text", "text": prompt},
		]
	return [
		{"type": "text", "text": prompt},
		{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
	]


def _vision_client():
	"""The IDP Settings client, when it is OpenAI or Anthropic and can see a page.

	Uses LLMClient.from_settings so the scan and the rest of IDP share one key,
	one model, and the same retry and budget checks.
	"""
	import frappe
	from idp.llm.client import LLMClient
	from idp.llm.model_registry import get_model_info

	try:
		doc = frappe.get_single("IDP Settings")
	except Exception:
		return None
	provider_name = (getattr(doc, "llm_provider", None) or "openai").strip()
	if provider_name not in {"openai", "anthropic"}:
		return None
	try:
		api_key = doc.get_password("llm_api_key", raise_exception=False)
	except Exception:
		api_key = None
	if not api_key:
		return None
	try:
		client = LLMClient.from_settings()
	except Exception:
		frappe.log_error(title="IDP vision client unavailable", message=frappe.get_traceback())
		return None
	info = get_model_info(client.default_model or "")
	if info.provider != "unknown" and not info.supports_vision:
		return None
	return client


def _page_images(file_path: str) -> list[tuple[int, str]]:
	if file_path.lower().endswith(".pdf"):
		return _render_pdf(file_path)
	return [(1, file_path)]


def _render_pdf(file_path: str) -> list[tuple[int, str]]:
	"""Render pages with pypdfium2, installed with the app via pyproject.toml."""
	from idp.core.exceptions import ExtractionError

	try:
		import pypdfium2 as pdfium
	except ImportError as exc:
		raise ExtractionError(
			"pypdfium2 is not installed. Run bench setup requirements to install IDP dependencies."
		) from exc

	pdf = pdfium.PdfDocument(file_path)
	folder = tempfile.mkdtemp(prefix="idp-vision-")
	pages: list[tuple[int, str]] = []
	try:
		count = min(len(pdf), _MAX_PAGES)
		for index in range(count):
			page = pdf[index]
			bitmap = page.render(scale=200 / 72)
			image = bitmap.to_pil()
			dest = os.path.join(folder, f"page-{index + 1}.png")
			image.save(dest, format="PNG")
			bitmap.close()
			page.close()
			pages.append((index + 1, dest))
	except Exception:
		import shutil

		shutil.rmtree(folder, ignore_errors=True)
		raise
	finally:
		pdf.close()
	return pages


def _read_page(client, image_path: str) -> str:
	prepared = _fit_image(image_path)
	try:
		response = client.chat(
			[{"role": "user", "content": image_content(client.provider, prepared, _PROMPT)}],
			temperature=0.0,
			model=client.default_model,
		)
	finally:
		if prepared != image_path:
			_remove(prepared)
	return response.content or ""


def _fit_image(image_path: str) -> str:
	from PIL import Image

	img = Image.open(image_path)
	long_edge = max(img.size)
	if long_edge <= _LONG_EDGE:
		return image_path
	scale = _LONG_EDGE / float(long_edge)
	img = img.convert("RGB").resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
	dest = os.path.join(os.path.dirname(image_path), f"vision-{os.path.basename(image_path)}")
	img.save(dest, format="PNG")
	return dest


def _cleanup(source: str, pages: list[tuple[int, str]]) -> None:
	folders: set[str] = set()
	for _number, image in pages:
		if image != source:
			folders.add(os.path.dirname(image))
			_remove(image)
	for folder in folders:
		try:
			os.rmdir(folder)
		except OSError:
			pass


def _read_bytes(path: str) -> bytes:
	with open(path, "rb") as handle:
		return handle.read()


def _remove(path: str) -> None:
	try:
		os.remove(path)
	except OSError:
		pass
