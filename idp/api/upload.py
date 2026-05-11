# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""File upload endpoint for IDP processing.

Accepts multipart form data, validates MIME type and file size,
stores the file as a private Frappe File record, and returns
metadata for downstream extraction.
"""

import frappe

from idp.core.constants import MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, SUPPORTED_MIME_TYPES
from idp.core.logger import get_logger
from idp.extractors.base import resolve_file

logger = get_logger("idp.api.upload")


@frappe.whitelist()
def upload_document() -> dict:
	"""Upload a document for IDP processing.

	Reads the uploaded file from ``frappe.request.files``, validates its
	MIME type and size, saves it as a **private** Frappe File record, and
	returns metadata the frontend needs for subsequent extraction.

	Returns:
		dict with keys:
			- ``success``: bool
			- ``file_url``: str (Frappe file URL, e.g. ``/private/files/invoice.pdf``)
			- ``file_name``: str
			- ``mime_type``: str
			- ``size``: int (bytes)
	"""
	# 1. Read file from request
	if "file" not in frappe.request.files:
		frappe.throw("No file uploaded. Please attach a file.", frappe.ValidationError)

	uploaded = frappe.request.files["file"]
	file_name = frappe.safe_decode(uploaded.filename or "document")
	content = uploaded.read()
	content_type = uploaded.content_type or "application/octet-stream"

	# 2. Validate file size
	file_size = len(content)
	if file_size > MAX_FILE_SIZE_BYTES:
		frappe.throw(
			f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds the maximum "
			f"allowed size ({MAX_FILE_SIZE_MB} MB).",
			frappe.ValidationError,
		)

	if file_size == 0:
		frappe.throw("Uploaded file is empty.", frappe.ValidationError)

	# 3. Validate MIME type
	if content_type not in SUPPORTED_MIME_TYPES:
		# Try to detect from extension as a fallback
		import os

		from idp.core.constants import EXTENSION_TO_MIME

		_, ext = os.path.splitext(file_name)
		content_type = EXTENSION_TO_MIME.get(ext.lower(), content_type)

	if content_type not in SUPPORTED_MIME_TYPES:
		supported = ", ".join(sorted(SUPPORTED_MIME_TYPES.values()))
		frappe.throw(
			f"Unsupported file type: {content_type}. Supported types: {supported}",
			frappe.ValidationError,
		)

	# 4. Save as private Frappe File
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
		}
	)
	file_doc.flags.ignore_permissions = True
	file_doc.save()

	# 5. Verify the file is accessible via resolve_file
	try:
		resolve_file(file_doc.file_url)
	except Exception as exc:
		logger.warning(f"File saved but resolve check failed: {exc}")

	logger.info(f"Uploaded {file_name} ({file_size} bytes, {content_type}) -> {file_doc.file_url}")

	return {
		"success": True,
		"file_url": file_doc.file_url,
		"file_name": file_doc.file_name,
		"mime_type": content_type,
		"size": file_size,
	}
