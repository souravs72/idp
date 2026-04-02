# IDP Core — Foundation package for Intelligent Document Processing
#
# Provides: config, constants, exceptions, logger

from idp.core.config import (
	get_confidence_threshold,
	get_default_company,
	get_idp_settings,
	get_ocr_language,
	is_feature_enabled,
)
from idp.core.constants import (
	DEFAULT_CONFIDENCE_THRESHOLD,
	LOW_CONFIDENCE_THRESHOLD,
	MAX_FILE_SIZE_MB,
	MAX_PAGES_PER_PDF,
	OCR_LANGUAGES,
	SUPPORTED_DOCTYPES,
	SUPPORTED_MIME_TYPES,
)
from idp.core.exceptions import (
	ExtractionError,
	FileTooLargeError,
	IDPError,
	MappingError,
	MissingMasterError,
	OCRError,
	UnsupportedFormatError,
	ValidationError,
)
from idp.core.logger import get_logger, log_extraction, log_ocr_result

__all__ = [
	"DEFAULT_CONFIDENCE_THRESHOLD",
	"LOW_CONFIDENCE_THRESHOLD",
	"MAX_FILE_SIZE_MB",
	"MAX_PAGES_PER_PDF",
	"OCR_LANGUAGES",
	"SUPPORTED_DOCTYPES",
	"SUPPORTED_MIME_TYPES",
	"ExtractionError",
	"FileTooLargeError",
	"IDPError",
	"MappingError",
	"MissingMasterError",
	"OCRError",
	"UnsupportedFormatError",
	"ValidationError",
	"get_confidence_threshold",
	"get_default_company",
	"get_idp_settings",
	"get_logger",
	"get_ocr_language",
	"is_feature_enabled",
	"log_extraction",
	"log_ocr_result",
]
