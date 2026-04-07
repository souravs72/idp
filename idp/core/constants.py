# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""App-wide constants for the IDP module.

Defines supported MIME types, target DocTypes, OCR languages,
file-size limits, and confidence thresholds used across the pipeline.
"""

# ---------------------------------------------------------------------------
# Supported MIME types and their extractor mappings
# ---------------------------------------------------------------------------
SUPPORTED_MIME_TYPES: dict[str, str] = {
	"application/pdf": "pdf",
	"image/png": "image",
	"image/jpeg": "image",
	"image/webp": "image",
	"image/tiff": "image",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
	"application/vnd.ms-excel": "excel",
	"text/csv": "csv",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# Reverse lookup: file extension -> MIME type
EXTENSION_TO_MIME: dict[str, str] = {
	".pdf": "application/pdf",
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".webp": "image/webp",
	".tiff": "image/tiff",
	".tif": "image/tiff",
	".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	".xls": "application/vnd.ms-excel",
	".csv": "text/csv",
	".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# ---------------------------------------------------------------------------
# Supported target DocTypes for extraction
# ---------------------------------------------------------------------------
SUPPORTED_DOCTYPES: list[str] = [
	"Opportunity",
	"Sales Invoice",
	"Purchase Invoice",
	"Quotation",
	"Sales Order",
	"Supplier Quotation",
	"Purchase Order",
	"Delivery Note",
	"Purchase Receipt",
	"Payment Entry",
	"Journal Entry",
]

# ---------------------------------------------------------------------------
# PaddleOCR supported languages (subset of 111)
# ---------------------------------------------------------------------------
OCR_LANGUAGES: dict[str, str] = {
	"en": "English",
	"ch": "Chinese",
	"hi": "Hindi",
	"ar": "Arabic",
	"fr": "French",
	"de": "German",
	"ja": "Japanese",
	"ko": "Korean",
	"es": "Spanish",
	"ta": "Tamil",
	"te": "Telugu",
	"pt": "Portuguese",
}

# ---------------------------------------------------------------------------
# File size limits
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_MB: int = 25
MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES_PER_PDF: int = 50

# ---------------------------------------------------------------------------
# OCR confidence thresholds
# ---------------------------------------------------------------------------
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.70
LOW_CONFIDENCE_THRESHOLD: float = 0.50

# ---------------------------------------------------------------------------
# DocType field types eligible for extraction
# ---------------------------------------------------------------------------
EXTRACTABLE_FIELD_TYPES: list[str] = [
	"Data",
	"Link",
	"Date",
	"Currency",
	"Float",
	"Int",
	"Select",
	"Text",
	"Small Text",
	"Long Text",
	"Check",
]

# ---------------------------------------------------------------------------
# Fields auto-populated by ERPNext controllers (skip in required-field checks)
# ---------------------------------------------------------------------------
AUTO_POPULATED_FIELDS: set[str] = {
	# Naming
	"naming_series",
	"name",
	"amended_from",
	# Accounting defaults — set by controller based on party/company
	"credit_to",
	"debit_to",
	"party_account_currency",
	"is_opening",
	"is_return",
	# Company — set from user session / form context
	"company",
	# Status / workflow
	"status",
	"docstatus",
	# Conversion rates — default to 1.0
	"conversion_rate",
	"plc_conversion_rate",
	# Timestamps
	"creation",
	"modified",
	"owner",
	"modified_by",
}

# Field types to exclude (layout / non-data fields)
EXCLUDED_FIELD_TYPES: list[str] = [
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Table",
	"Table MultiSelect",
	"Heading",
	"Button",
	"Fold",
]
