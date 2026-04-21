# IDP — Manual Testing Guide

Step-by-step tests for each implemented phase.
Run all commands from the **bench directory**: `cd /path/to/frappe-bench-test`

**Site:** `test.local` (adjust if your site name differs)

---

## Phase 1: Core Infrastructure

### Test 1.1 — Constants import

```bash
bench --site test.local execute idp.core.constants --args '[]' --kwargs '{}' 2>/dev/null
# OR use bench console:
bench --site test.local console
```

```python
from idp.core.constants import (
    SUPPORTED_MIME_TYPES, SUPPORTED_DOCTYPES, OCR_LANGUAGES,
    MAX_FILE_SIZE_MB, MAX_PAGES_PER_PDF,
    DEFAULT_CONFIDENCE_THRESHOLD, LOW_CONFIDENCE_THRESHOLD,
    EXTRACTABLE_FIELD_TYPES, EXTENSION_TO_MIME,
)

print("MIME types:", len(SUPPORTED_MIME_TYPES))        # Expected: 9
print("DocTypes:", len(SUPPORTED_DOCTYPES))            # Expected: 9
print("OCR languages:", len(OCR_LANGUAGES))            # Expected: 12
print("Max file size:", MAX_FILE_SIZE_MB)              # Expected: 25
print("Max pages:", MAX_PAGES_PER_PDF)                 # Expected: 50
print("Default confidence:", DEFAULT_CONFIDENCE_THRESHOLD)  # Expected: 0.70
print("Low confidence:", LOW_CONFIDENCE_THRESHOLD)     # Expected: 0.50
print("Extractable types:", len(EXTRACTABLE_FIELD_TYPES))   # Expected: 11
print("Extension map:", len(EXTENSION_TO_MIME))        # Expected: 11
print("PDF mime:", SUPPORTED_MIME_TYPES["application/pdf"])  # Expected: "pdf"
print(".xlsx ext:", EXTENSION_TO_MIME[".xlsx"])         # Expected: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
```

**Expected:** All values print without errors, counts match comments.

---

### Test 1.2 — Exceptions hierarchy

```python
from idp.core.exceptions import (
    IDPError, ExtractionError, OCRError, ValidationError,
    MappingError, UnsupportedFormatError, FileTooLargeError, MissingMasterError,
)

# All should be subclasses of IDPError
for exc_cls in [ExtractionError, OCRError, ValidationError, MappingError,
                UnsupportedFormatError, FileTooLargeError, MissingMasterError]:
    assert issubclass(exc_cls, IDPError), f"{exc_cls.__name__} is not a subclass of IDPError"
    print(f"  {exc_cls.__name__}: OK")

# Test details kwarg
try:
    raise FileTooLargeError("too big", details={"size_mb": 30})
except IDPError as e:
    print(f"Caught: {e}, details={e.details}")
    assert e.details["size_mb"] == 30
    # Expected: Caught: too big, details={'size_mb': 30}

print("All exception tests passed")
```

---

### Test 1.3 — Config (safe defaults before DocType exists)

```python
from idp.core.config import (
    get_idp_settings, get_default_company, is_feature_enabled,
    get_ocr_language, get_confidence_threshold,
)

settings = get_idp_settings()
print("Settings type:", type(settings))          # Expected: <class 'dict'>
print("Enabled:", settings.get("enabled"))       # Expected: 1
print("OCR lang:", settings.get("default_ocr_language"))  # Expected: "en"

lang = get_ocr_language()
print("OCR language:", lang)                     # Expected: "en"

threshold = get_confidence_threshold()
print("Confidence threshold:", threshold)         # Expected: 0.7

# Feature flags should default to True
print("OCR enabled:", is_feature_enabled("enable_ocr"))            # Expected: True
print("PDF enabled:", is_feature_enabled("enable_pdf"))            # Expected: True
print("Write ops:", is_feature_enabled("enable_write_operations")) # Expected: False (0 in defaults)

company = get_default_company()
print("Default company:", repr(company))          # Expected: company name or ""
```

---

### Test 1.4 — Logger

```python
from idp.core.logger import get_logger, log_extraction, log_ocr_result

logger = get_logger("idp.test")
print("Logger name:", logger.name)  # Expected: contains "idp.test"

# These should log without errors
log_extraction("/files/test.pdf", "Purchase Invoice", "success", 1500)
log_extraction("/files/test.pdf", "Purchase Invoice", "failed", 500, error="timeout")
log_ocr_result("/files/test.pdf", pages=3, avg_confidence=0.85, language="en")
log_ocr_result("/files/test.pdf", pages=1, avg_confidence=0.40, language="en")
print("Logger tests passed")
```

---

## Phase 2: PaddleOCR Integration & OCR Engine

> **Note:** PaddleOCR is NOT installed in the current environment.
> These tests verify the module loads and error handling works correctly.
> Full OCR tests require `pip install paddleocr`.

### Test 2.1 — Data models import

```python
from idp.idp.ocr_engine import (
    TextBlock, Table, LayoutRegion, LayoutAnalysis, OCRResult,
)

# Create instances
tb = TextBlock(text="Hello", confidence=0.95, bbox=[[0,0],[100,0],[100,30],[0,30]])
print(f"TextBlock: {tb.text}, conf={tb.confidence}")
# Expected: TextBlock: Hello, conf=0.95

tbl = Table(rows=[["A", "B"], ["1", "2"]])
print(f"Table rows: {len(tbl.rows)}")
# Expected: Table rows: 2

lr = LayoutRegion(region_type="title", bbox=[[0,0],[100,30]], content="Header")
la = LayoutAnalysis(regions=[lr])
print(f"Layout regions: {len(la.regions)}")
# Expected: Layout regions: 1

ocr = OCRResult(page_number=1, text_blocks=[tb], tables=[tbl], layout=la,
                average_confidence=0.95, language="en", processing_time_ms=500)
print(f"OCR page={ocr.page_number}, blocks={len(ocr.text_blocks)}, conf={ocr.average_confidence}")
# Expected: OCR page=1, blocks=1, conf=0.95
print("Data model tests passed")
```

### Test 2.2 — OCR engine graceful error (PaddleOCR not installed)

```python
from idp.idp.ocr_engine import get_ocr_engine, get_structure_engine
from idp.core.exceptions import OCRError

try:
    get_ocr_engine("en")
    print("ERROR: Should have raised OCRError")
except OCRError as e:
    print(f"Correctly raised OCRError: {e}")
    assert "not installed" in str(e).lower()
    # Expected: OCRError with install instructions

try:
    get_structure_engine("en")
    print("ERROR: Should have raised OCRError")
except OCRError as e:
    print(f"Correctly raised OCRError: {e}")
    assert "not installed" in str(e).lower()
print("OCR engine error handling tests passed")
```

### Test 2.3 — Image preprocessing (Pillow only, no OCR needed)

```python
import tempfile, os
from PIL import Image
from idp.idp.ocr_engine import preprocess_image

# Create a small test image
img = Image.new("RGB", (200, 100), color="white")
fd, tmp_path = tempfile.mkstemp(suffix=".png")
os.close(fd)
img.save(tmp_path)

result_path = preprocess_image(tmp_path)
result_img = Image.open(result_path)
print(f"Original: 200x100 -> Preprocessed: {result_img.width}x{result_img.height}")
# Expected: width >= 1500 (upscaled), mode = L (grayscale)
print(f"Mode: {result_img.mode}")
# Expected: L
assert result_img.width >= 1500
assert result_img.mode == "L"

# Cleanup
os.remove(tmp_path)
os.remove(result_path)
print("Image preprocessing tests passed")
```

---

## Phase 3: Content Extractors

### Test 3.1 — ExtractionResult and base imports

```python
from idp.idp.extractors.base import ExtractionResult, BaseExtractor

er = ExtractionResult(
    content_type="text",
    text="Hello world",
    metadata={"file_name": "test.pdf"},
)
print(f"Type: {er.content_type}, text: {er.text}")
# Expected: Type: text, text: Hello world

print(f"BaseExtractor is abstract: {BaseExtractor.__abstractmethods__}")
# Expected: frozenset({'extract', 'supports_mime_type'})
print("Base extractor tests passed")
```

### Test 3.2 — CSV Extractor (no external dependencies)

```python
import tempfile, os
from idp.idp.extractors.extractor import CSVExtractor

# Create a test CSV
csv_content = "Item,Qty,Rate,Amount\nWidget A,10,500.00,5000.00\nWidget B,5,300.00,1500.00\n"
fd, csv_path = tempfile.mkstemp(suffix=".csv")
os.close(fd)
with open(csv_path, "w") as f:
    f.write(csv_content)

ext = CSVExtractor()
print("Supports text/csv:", ext.supports_mime_type("text/csv"))        # Expected: True
print("Supports pdf:", ext.supports_mime_type("application/pdf"))       # Expected: False

result = ext.extract(csv_path)
print(f"Content type: {result.content_type}")    # Expected: tabular
print(f"Tables: {len(result.tables)}")            # Expected: 1
print(f"Rows: {len(result.tables[0])}")           # Expected: 3 (header + 2 data)
print(f"Header: {result.tables[0][0]}")           # Expected: ['Item', 'Qty', 'Rate', 'Amount']
print(f"Row 1: {result.tables[0][1]}")            # Expected: ['Widget A', '10', '500.00', '5000.00']
print(f"Metadata: {result.metadata}")             # Expected: file_name, mime_type, row_count

os.remove(csv_path)
print("CSV extractor tests passed")
```

### Test 3.3 — Excel Extractor

```python
import tempfile, os
from openpyxl import Workbook
from idp.idp.extractors.extractor import ExcelExtractor

# Create a test Excel file
wb = Workbook()
ws = wb.active
ws.append(["Item", "Qty", "Rate"])
ws.append(["Widget A", 10, 500.00])
ws.append(["Widget B", 5, 300.00])
fd, xlsx_path = tempfile.mkstemp(suffix=".xlsx")
os.close(fd)
wb.save(xlsx_path)

ext = ExcelExtractor()
result = ext.extract(xlsx_path)
print(f"Content type: {result.content_type}")    # Expected: tabular
print(f"Tables: {len(result.tables)}")            # Expected: 1
print(f"Rows: {len(result.tables[0])}")           # Expected: 3
print(f"Header: {result.tables[0][0]}")           # Expected: ['Item', 'Qty', 'Rate']
print(f"Row 1: {result.tables[0][1]}")            # Expected: ['Widget A', '10', '500.0']

os.remove(xlsx_path)
print("Excel extractor tests passed")
```

### Test 3.4 — DOCX Extractor

```python
import tempfile, os
from docx import Document
from idp.idp.extractors.extractor import DocxExtractor

# Create a test DOCX file
doc = Document()
doc.add_heading("Invoice #INV-001", level=1)
doc.add_paragraph("Supplier: Tara Technologies")
doc.add_paragraph("Date: 2026-04-01")
table = doc.add_table(rows=3, cols=3)
table.cell(0, 0).text = "Item"
table.cell(0, 1).text = "Qty"
table.cell(0, 2).text = "Rate"
table.cell(1, 0).text = "Widget A"
table.cell(1, 1).text = "10"
table.cell(1, 2).text = "500"
table.cell(2, 0).text = "Widget B"
table.cell(2, 1).text = "5"
table.cell(2, 2).text = "300"
fd, docx_path = tempfile.mkstemp(suffix=".docx")
os.close(fd)
doc.save(docx_path)

ext = DocxExtractor()
result = ext.extract(docx_path)
print(f"Content type: {result.content_type}")    # Expected: mixed
print(f"Text contains supplier: {'Tara Technologies' in result.text}")  # Expected: True
print(f"Tables: {len(result.tables)}")            # Expected: 1
print(f"Table rows: {len(result.tables[0])}")     # Expected: 3
print(f"Metadata: {result.metadata}")

os.remove(docx_path)
print("DOCX extractor tests passed")
```

### Test 3.5 — File resolution error handling

```python
from idp.idp.extractors.base import resolve_file
from idp.core.exceptions import ExtractionError, UnsupportedFormatError

# Non-existent file
try:
    resolve_file("/files/does_not_exist.pdf")
except ExtractionError as e:
    print(f"Correctly raised ExtractionError: {e}")
    # Expected: "File not found on disk"

print("File resolution tests passed")
```

### Test 3.6 — Factory dispatcher (MIME detection)

```python
from idp.idp.extractors.base import _detect_mime_type

print(_detect_mime_type("/path/to/file.pdf"))   # Expected: application/pdf
print(_detect_mime_type("/path/to/file.xlsx"))  # Expected: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
print(_detect_mime_type("/path/to/file.csv"))   # Expected: text/csv
print(_detect_mime_type("/path/to/file.docx"))  # Expected: application/vnd.openxmlformats-officedocument.wordprocessingml.document
print(_detect_mime_type("/path/to/file.png"))   # Expected: image/png
print(_detect_mime_type("/path/to/file.jpg"))   # Expected: image/jpeg
print("MIME detection tests passed")
```

---

## Phase 4: Schema Discovery & Field Mapping

### Test 4.1 — Schema discovery

```python
from idp.idp.mappers.base import get_doctype_schema, get_extractable_fields

schema = get_doctype_schema("Purchase Invoice")
print(f"DocType: {schema['doctype']}")               # Expected: Purchase Invoice
print(f"Fields count: {len(schema['fields'])}")       # Expected: > 0
print(f"Child tables: {list(schema['child_tables'].keys())}")  # Expected: contains 'items'

# Check items child table
items = schema["child_tables"].get("items", {})
print(f"Items DocType: {items.get('doctype')}")       # Expected: Purchase Invoice Item
print(f"Items fields: {len(items.get('fields', []))}")  # Expected: > 0

# Check extractable fields
ext_fields = get_extractable_fields("Purchase Invoice")
print(f"Extractable fields: {len(ext_fields)}")       # Expected: > 0
# All should be extractable types
for f in ext_fields:
    assert f["fieldtype"] in [
        "Data", "Link", "Date", "Currency", "Float", "Int",
        "Select", "Text", "Small Text", "Long Text", "Check",
    ], f"Unexpected type: {f['fieldtype']}"
print("Schema discovery tests passed")
```

### Test 4.2 — Date normalization

```python
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()

# Test various date formats
test_cases = [
    ("2026-04-02", "2026-04-02"),       # ISO
    ("02/04/2026", "2026-04-02"),       # DD/MM/YYYY
    ("02-Apr-2026", "2026-04-02"),      # DD-Mon-YYYY
    ("April 02, 2026", "2026-04-02"),   # Mon DD, YYYY
    ("02.04.2026", "2026-04-02"),       # DD.MM.YYYY
    ("15/01/26", "2026-01-15"),         # DD/MM/YY
]

for raw, expected in test_cases:
    result = fm._normalise_date(raw)
    status = "OK" if result == expected else f"FAIL (got {result})"
    print(f"  '{raw}' -> '{result}' {status}")

print("Date normalization tests passed")
```

### Test 4.3 — Number normalization

```python
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()

test_cases = [
    ("1,234.56", 1234.56),
    ("₹ 50,000.00", 50000.00),
    ("$1,234.56", 1234.56),
    ("1.234,56", 1234.56),           # European format
    ("Rs. 9,000", 9000.0),
    ("1,23,456.78", 123456.78),      # Indian lakhs
    ("500", 500.0),
]

for raw, expected in test_cases:
    result = fm._normalise_number(raw)
    status = "OK" if result == expected else f"FAIL (got {result})"
    print(f"  '{raw}' -> {result} {status}")

print("Number normalization tests passed")
```

### Test 4.4 — Label-value pair parsing

```python
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()

text = """Invoice No: INV-2026-001
Supplier: Tara Technologies
Date: 02-Apr-2026
Grand Total:   Rs. 59,000.00
Due Date: 15/04/2026"""

pairs = fm._parse_label_value_pairs(text)
for label, value in pairs:
    print(f"  '{label}' -> '{value}'")

# Expected output:
#   'Invoice No' -> 'INV-2026-001'
#   'Supplier' -> 'Tara Technologies'
#   'Date' -> '02-Apr-2026'
#   'Grand Total' -> 'Rs. 59,000.00'
#   'Due Date' -> '15/04/2026'
assert len(pairs) == 5
print("Label-value parsing tests passed")
```

### Test 4.5 — Header field matching

```python
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()
keywords = fm.FIELD_KEYWORDS["Purchase Invoice"]
schema_fields = [
    {"fieldname": "supplier", "fieldtype": "Link", "label": "Supplier", "reqd": 1, "options": "Supplier"},
    {"fieldname": "posting_date", "fieldtype": "Date", "label": "Date", "reqd": 1, "options": ""},
    {"fieldname": "grand_total", "fieldtype": "Currency", "label": "Grand Total", "reqd": 0, "options": ""},
    {"fieldname": "bill_no", "fieldtype": "Data", "label": "Bill No", "reqd": 0, "options": ""},
]

test_cases = [
    ("Supplier", "Tara Tech", "supplier"),
    ("Vendor", "Tara Tech", "supplier"),
    ("Invoice Date", "2026-04-01", "posting_date"),
    ("Grand Total", "50000", "grand_total"),
    ("Total Amount", "50000", "grand_total"),
    ("Invoice No", "INV-001", "bill_no"),
]

for label, value, expected in test_cases:
    result = fm._match_header_field(label, value, schema_fields, keywords)
    status = "OK" if result == expected else f"FAIL (got {result})"
    print(f"  '{label}' -> {result} {status}")

print("Header field matching tests passed")
```

### Test 4.6 — Column header matching for items

```python
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()
child_fields = [
    {"fieldname": "item_code", "fieldtype": "Link", "label": "Item Code", "reqd": 0, "options": "Item"},
    {"fieldname": "item_name", "fieldtype": "Data", "label": "Item Name", "reqd": 0, "options": ""},
    {"fieldname": "qty", "fieldtype": "Float", "label": "Qty", "reqd": 1, "options": ""},
    {"fieldname": "rate", "fieldtype": "Currency", "label": "Rate", "reqd": 1, "options": ""},
    {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "reqd": 1, "options": ""},
]

header_row = ["Item", "Quantity", "Unit Price", "Amount"]
col_map = fm._match_column_headers(header_row, child_fields)
print(f"Column mapping: {col_map}")
# Expected: {0: 'item_name', 1: 'qty', 2: 'rate', 3: 'amount'}

print("Column matching tests passed")
```

### Test 4.7 — Full mapping pipeline (end-to-end with mock data)

```python
from idp.idp.extractors.base import ExtractionResult
from idp.idp.mappers.mapper import FieldMapper

fm = FieldMapper()

# Simulate extracted data from a Purchase Invoice
extracted = ExtractionResult(
    content_type="mixed",
    text="""Supplier: Tara Technologies
Invoice No: INV-2026-042
Invoice Date: 02-Apr-2026
Due Date: 30/04/2026
Net Total: Rs. 50,000.00
Tax: Rs. 9,000.00
Grand Total: Rs. 59,000.00""",
    tables=[[
        ["Item", "Qty", "Rate", "Amount"],
        ["Widget A", "100", "500.00", "50000.00"],
    ]],
    metadata={"file_name": "invoice.pdf"},
)

result = fm.map_fields(extracted, "Purchase Invoice")
print(f"DocType: {result.doctype}")
print(f"Header fields: {result.header}")
print(f"Items: {result.items}")
print(f"Unmapped: {result.unmapped_fields}")
print(f"Confidence: {result.confidence_scores}")
print(f"Warnings: {result.warnings}")

# Verify key fields were mapped
assert "posting_date" in result.header or "bill_no" in result.header, "Expected some header fields mapped"
print("Full mapping pipeline test passed")
```

---

## Phase 5: Validators — Schema & Business Rules

### Test 5.1 — Data model imports

```python
from idp.idp.validators import (
    ValidationIssue, ValidationResult,
    validate_schema, resolve_links, validate_business_rules,
)

# ValidationIssue
issue = ValidationIssue(field="supplier", message="Required field missing", severity="error", value=None)
print(f"Issue: {issue.field} — {issue.message} [{issue.severity}]")
# Expected: Issue: supplier — Required field missing [error]

# ValidationResult defaults
result = ValidationResult()
print(f"is_valid: {result.is_valid}")             # Expected: True
print(f"errors: {result.errors}")                 # Expected: []
print(f"warnings: {result.warnings}")             # Expected: []
print(f"resolved_links: {result.resolved_links}") # Expected: {}
print(f"missing_masters: {result.missing_masters}")# Expected: []
print("Data model import tests passed")
```

---

### Test 5.2 — Business rules: date ordering

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.business_rules import validate_business_rules

# PASS: due_date after posting_date
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-01", "due_date": "2026-04-30"},
    items=[{"item_name": "Widget", "qty": 10, "rate": 100, "amount": 1000}],
)
issues = validate_business_rules(doc)
date_issues = [i for i in issues if "before" in i]
print(f"Date ordering (valid): {date_issues}")
# Expected: [] (no date ordering issues)

# FAIL: due_date before posting_date
doc2 = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-30", "due_date": "2026-04-01"},
    items=[{"item_name": "Widget", "qty": 10, "rate": 100, "amount": 1000}],
)
issues2 = validate_business_rules(doc2)
date_issues2 = [i for i in issues2 if "before" in i]
print(f"Date ordering (invalid): {date_issues2}")
# Expected: ["due_date (2026-04-01) is before posting_date (2026-04-30)"]
assert len(date_issues2) == 1
print("Date ordering tests passed")
```

---

### Test 5.3 — Business rules: line item presence

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.business_rules import validate_business_rules

# FAIL: Purchase Invoice with no items
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-01"},
    items=[],
)
issues = validate_business_rules(doc)
item_issues = [i for i in issues if "line item" in i.lower()]
print(f"No items: {item_issues}")
# Expected: ["At least one line item is required"]
assert len(item_issues) == 1

# PASS: Non-transaction doctype (no line items required)
doc2 = MappedDocument(
    doctype="Address",
    header={"address_line1": "123 Main St"},
    items=[],
)
issues2 = validate_business_rules(doc2)
item_issues2 = [i for i in issues2 if "line item" in i.lower()]
print(f"Non-transaction no items: {item_issues2}")
# Expected: [] (no issue, Address is not a transaction doctype)
assert len(item_issues2) == 0
print("Line item presence tests passed")
```

---

### Test 5.4 — Business rules: qty, rate, amount checks

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.business_rules import validate_business_rules

# FAIL: qty=0, negative rate, mismatched amount
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-01", "due_date": "2026-04-30"},
    items=[
        {"item_name": "A", "qty": 0, "rate": 100, "amount": 0},         # qty=0 error
        {"item_name": "B", "qty": 5, "rate": -10, "amount": -50},       # negative rate
        {"item_name": "C", "qty": 10, "rate": 100, "amount": 500},      # amount != qty*rate (1000)
    ],
)
issues = validate_business_rules(doc)
print("Issues found:")
for i in issues:
    print(f"  {i}")
# Expected issues include:
#   Row 1: qty must be greater than 0
#   Row 2: rate must be >= 0
#   Row 3: amount (500.0) != qty (10.0) x rate (100.0) = 1000.0

qty_issues = [i for i in issues if "qty" in i.lower() and "greater" in i.lower()]
rate_issues = [i for i in issues if "rate must" in i.lower()]
amount_issues = [i for i in issues if "!=" in i and "rate" in i]
assert len(qty_issues) >= 1, f"Expected qty issue, got: {qty_issues}"
assert len(rate_issues) >= 1, f"Expected rate issue, got: {rate_issues}"
assert len(amount_issues) >= 1, f"Expected amount mismatch, got: {amount_issues}"
print("Qty/rate/amount tests passed")
```

---

### Test 5.5 — Business rules: total checks

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.business_rules import validate_business_rules

# PASS: totals match
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "net_total": 1500,
        "total_taxes_and_charges": 270,
        "grand_total": 1770,
    },
    items=[
        {"item_name": "A", "qty": 10, "rate": 100, "amount": 1000},
        {"item_name": "B", "qty": 5, "rate": 100, "amount": 500},
    ],
)
issues = validate_business_rules(doc)
total_issues = [i for i in issues if "net_total" in i or "grand_total" in i]
print(f"Matching totals: {total_issues}")
# Expected: [] (all totals match)

# FAIL: net_total mismatch
doc2 = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "net_total": 9999,   # actual sum is 1500
        "grand_total": 10269,
        "total_taxes_and_charges": 270,
    },
    items=[
        {"item_name": "A", "qty": 10, "rate": 100, "amount": 1000},
        {"item_name": "B", "qty": 5, "rate": 100, "amount": 500},
    ],
)
issues2 = validate_business_rules(doc2)
net_issues = [i for i in issues2 if "net_total" in i and "sum" in i.lower()]
print(f"Mismatched net_total: {net_issues}")
# Expected: ["net_total (9999.0) does not match sum of item amounts (1500.0)"]
assert len(net_issues) >= 1
print("Total check tests passed")
```

---

### Test 5.6 — Business rules: currency validation

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.business_rules import validate_business_rules

# PASS: valid currency
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-01", "due_date": "2026-04-30", "currency": "INR"},
    items=[{"item_name": "A", "qty": 10, "rate": 100, "amount": 1000}],
)
issues = validate_business_rules(doc)
currency_issues = [i for i in issues if "currency" in i.lower()]
print(f"Valid currency: {currency_issues}")
# Expected: [] (INR exists in ERPNext)

# FAIL: bogus currency
doc2 = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "2026-04-01", "due_date": "2026-04-30", "currency": "XYZZY"},
    items=[{"item_name": "A", "qty": 10, "rate": 100, "amount": 1000}],
)
issues2 = validate_business_rules(doc2)
currency_issues2 = [i for i in issues2 if "currency" in i.lower()]
print(f"Invalid currency: {currency_issues2}")
# Expected: ['Currency "XYZZY" does not exist in ERPNext']
assert len(currency_issues2) >= 1
print("Currency validation tests passed")
```

---

### Test 5.7 — Schema validation: required fields and type checks

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.schema_validator import validate_schema

# Test with a mostly-empty header — should report missing required fields
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"posting_date": "not-a-date", "grand_total": "abc"},
    items=[],
)
result = validate_schema(doc)
print(f"is_valid: {result.is_valid}")   # Expected: False (missing required fields + type errors)
print(f"Errors ({len(result.errors)}):")
for e in result.errors:
    print(f"  [{e.severity}] {e.field}: {e.message}")
# Expected: several errors including:
#   - Required field "Supplier" is missing
#   - "not-a-date" is not a valid date
#   - "abc" is not a valid number

type_errors = [e for e in result.errors if "not a valid" in e.message]
required_errors = [e for e in result.errors if "Required field" in e.message]
print(f"Type errors: {len(type_errors)}, Required errors: {len(required_errors)}")
assert len(type_errors) >= 1, "Expected at least one type validation error"
assert len(required_errors) >= 1, "Expected at least one required field error"
print("Schema validation tests passed")
```

---

### Test 5.8 — Schema validation: Select options and Data length

```python
from idp.idp.validators.schema_validator import (
    ValidationResult, _check_select_options, _check_data_lengths,
)

result = ValidationResult()

# Test Select: simulate a field with known options
mock_fields = [
    {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "Draft\nSubmitted\nCancelled"},
]

# Valid value
_check_select_options({"status": "Draft"}, mock_fields, result)
print(f"Valid select warnings: {len(result.warnings)}")  # Expected: 0

# Invalid value
_check_select_options({"status": "Bogus"}, mock_fields, result)
print(f"Invalid select warnings: {len(result.warnings)}")  # Expected: 1
print(f"Warning: {result.warnings[0].message}")
# Expected: '"Bogus" is not a valid option for Status (allowed: Draft, Submitted, Cancelled)'

# Test Data length
result2 = ValidationResult()
long_fields = [
    {"fieldname": "description", "fieldtype": "Data", "label": "Description"},
]
_check_data_lengths({"description": "x" * 200}, long_fields, result2)
print(f"Data length warnings: {len(result2.warnings)}")  # Expected: 1
print(f"Warning: {result2.warnings[0].message}")
# Expected: 'Value for "Description" is 200 chars (max 140)'
print("Select and Data length tests passed")
```

---

### Test 5.9 — Link resolution

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators.schema_validator import resolve_links

# Test with known values — requires existing master data
# Using a supplier that likely exists in your test.local site
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"supplier": "Wind Power LLC", "currency": "INR"},
    items=[],
)

resolved = resolve_links(doc)
print(f"Resolved links: {resolved}")
# Expected: {"supplier": "Wind Power LLC"} if the supplier exists,
# or {} if it doesn't exist in your site

# The currency field is not a Link type (it's a Link to Currency),
# so it should also be resolved if "INR" exists
if "currency" in resolved:
    print(f"Currency resolved to: {resolved['currency']}")

print("Link resolution tests passed")
```

> **Note:** Test 5.9 depends on master data in your site. Adjust the
> supplier name to match an existing record, or create one first via
> ERPNext UI.

---

### Test 5.10 — Full validation pipeline (combined)

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.validators import validate_schema, validate_business_rules

# A well-formed Purchase Invoice
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": "Wind Power LLC",
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "currency": "INR",
        "net_total": 1500,
        "total_taxes_and_charges": 270,
        "grand_total": 1770,
    },
    items=[
        {"item_name": "Widget A", "qty": 10, "rate": 100, "amount": 1000},
        {"item_name": "Widget B", "qty": 5, "rate": 100, "amount": 500},
    ],
)

# Schema validation
schema_result = validate_schema(doc)
print(f"Schema valid: {schema_result.is_valid}")
print(f"Schema errors: {len(schema_result.errors)}")
print(f"Schema warnings: {len(schema_result.warnings)}")
print(f"Resolved links: {schema_result.resolved_links}")
print(f"Missing masters: {schema_result.missing_masters}")

# Business rules
biz_issues = validate_business_rules(doc)
print(f"Business rule issues: {biz_issues}")
# Expected: [] or minimal issues (depends on fiscal year setup)

# Combined: a document passes if schema is valid and no business rule errors
if schema_result.is_valid and not biz_issues:
    print("RESULT: Document is ready for creation")
elif schema_result.is_valid and biz_issues:
    print(f"RESULT: Schema OK, but {len(biz_issues)} business rule warning(s)")
else:
    print(f"RESULT: Schema invalid with {len(schema_result.errors)} error(s)")

print("Full validation pipeline test passed")
```

> **Note:** Adjust supplier name and ensure a Fiscal Year covers 2026-04-01
> in your test site for clean results.

---

## Phase 6: Document Creator — Mapped Data to ERPNext Documents

> **Important:** Phase 6 tests create actual records in the database.
> Run these on a **test site only** (`test.local`).  Some tests auto-create
> Supplier/Item records — clean up afterwards if needed.

### Test 6.1 — Imports

```python
from idp.idp.mappers import create_document, auto_create_missing_masters
from idp.idp.mappers.document_creator import (
    _find_missing_masters, _build_doc_dict, _preserve_text_fields,
    _get_primary_child_fieldname,
)
print("create_document:", create_document)
print("auto_create_missing_masters:", auto_create_missing_masters)
print("_find_missing_masters:", _find_missing_masters)
print("_build_doc_dict:", _build_doc_dict)
print("Imports OK")
# Expected: All functions import without error
```

---

### Test 6.2 — Build doc dict (no DB operations)

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import _build_doc_dict

doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": "Wind Power LLC",
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "currency": "INR",
        "bill_no": "VENDOR-INV-001",
        "remarks": "Test invoice from IDP",
    },
    items=[
        {"item_name": "Widget A", "qty": 10, "rate": 100, "amount": 1000},
        {"item_name": "Widget B", "qty": 5, "rate": 200, "amount": 1000},
    ],
)

result = _build_doc_dict(doc, "Your Company Name")
print(f"doctype: {result['doctype']}")
# Expected: Purchase Invoice
print(f"supplier: {result.get('supplier')}")
# Expected: Wind Power LLC
print(f"posting_date: {result.get('posting_date')}")
# Expected: 2026-04-01
print(f"company: {result.get('company')}")
# Expected: Your Company Name (or whatever company was passed)
print(f"items count: {len(result.get('items', []))}")
# Expected: 2
if result.get("items"):
    print(f"item 1 doctype: {result['items'][0].get('doctype')}")
    # Expected: Purchase Invoice Item
    print(f"item 1 qty: {result['items'][0].get('qty')}")
    # Expected: 10
print("Build doc dict test passed")
```

---

### Test 6.3 — Find missing masters

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import _find_missing_masters

# Use a supplier name that does NOT exist in your site
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"supplier": "ZZZ-Nonexistent-Supplier-XYZ"},
    items=[
        {"item_code": "ZZZ-FAKE-ITEM-999", "qty": 1, "rate": 100, "amount": 100},
    ],
)

missing = _find_missing_masters(doc, "")
print(f"Missing count: {len(missing)}")
# Expected: 2 (one Supplier, one Item)
for m in missing:
    print(f"  {m['doctype']}: {m['value']} (field: {m['fieldname']})")
# Expected:
#   Supplier: ZZZ-Nonexistent-Supplier-XYZ (field: supplier)
#   Item: ZZZ-FAKE-ITEM-999 (field: item_code)

assert len(missing) >= 1, "Expected at least one missing master"
assert any(m["doctype"] == "Supplier" for m in missing)
print("Find missing masters test passed")
```

---

### Test 6.4 — Auto-create missing masters

```python
import frappe
from idp.idp.mappers.document_creator import auto_create_missing_masters

# Create a unique supplier name for testing
test_supplier = "IDP-Test-Supplier-AutoCreate"
test_item = "IDP-Test-Item-AutoCreate"

# Clean up any leftovers from previous runs
if frappe.db.exists("Supplier", test_supplier):
    frappe.delete_doc("Supplier", test_supplier, force=True)
if frappe.db.exists("Item", test_item):
    frappe.delete_doc("Item", test_item, force=True)
frappe.db.commit()

missing = [
    {"doctype": "Supplier", "value": test_supplier, "fieldname": "supplier"},
    {"doctype": "Item", "value": test_item, "fieldname": "item_code"},
]

result = auto_create_missing_masters(missing, "")
print(f"Created: {result['created']}")
print(f"Failed: {result['failed']}")
# Expected: Created: [{"doctype": "Supplier", ...}, {"doctype": "Item", ...}]
# Expected: Failed: []

assert len(result["created"]) == 2, f"Expected 2 created, got {len(result['created'])}"
assert len(result["failed"]) == 0, f"Expected 0 failed, got {result['failed']}"

# Verify they exist
assert frappe.db.exists("Supplier", test_supplier), "Supplier not created"
assert frappe.db.exists("Item", test_item), "Item not created"
print("Auto-create masters test passed")

# Cleanup
frappe.delete_doc("Supplier", test_supplier, force=True)
frappe.delete_doc("Item", test_item, force=True)
frappe.db.commit()
print("Cleanup done")
```

---

### Test 6.5 — create_document: validation error path

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import create_document
from idp.core.exceptions import ValidationError

# Empty header should fail schema validation
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={},
    items=[],
)

try:
    create_document(doc, company="")
    print("ERROR: Should have raised ValidationError")
except ValidationError as e:
    print(f"Correctly raised ValidationError: {e}")
    print(f"Details: {e.details}")
    # Expected: "Schema validation failed with N error(s)"
    assert "errors" in e.details
    print("Validation error path test passed")
```

---

### Test 6.6 — create_document: missing master error path

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import create_document
from idp.core.exceptions import MissingMasterError

doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": "ZZZ-Nonexistent-Supplier-For-Test",
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
    },
    items=[
        {"item_name": "Widget", "qty": 10, "rate": 100, "amount": 1000},
    ],
)

try:
    create_document(doc, company="", create_missing_masters=False, skip_validation=True)
    print("ERROR: Should have raised MissingMasterError")
except MissingMasterError as e:
    print(f"Correctly raised MissingMasterError: {e}")
    print(f"Details: {e.details}")
    # Expected: "1 missing master record(s) — set create_missing_masters=True..."
    assert "missing" in e.details
    print("Missing master error path test passed")
```

---

### Test 6.7 — create_document: full end-to-end (creates a Draft PI)

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import create_document

# Ensure the supplier exists (use one from your site or create one)
test_supplier = "Wind Power LLC"
if not frappe.db.exists("Supplier", test_supplier):
    # Create a test supplier
    frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": test_supplier,
        "supplier_group": "All Supplier Groups",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

# Get first company
company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": test_supplier,
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "currency": "INR",
        "bill_no": "IDP-E2E-TEST-001",
        "remarks": "Created by IDP Phase 6 test",
    },
    items=[
        {"item_name": "Widget A", "qty": 10, "rate": 100, "amount": 1000},
        {"item_name": "Widget B", "qty": 5, "rate": 200, "amount": 1000},
    ],
)

result = create_document(doc, company=company, create_missing_masters=True, skip_validation=True)
print(f"Success: {result['success']}")
# Expected: True
print(f"DocType: {result['doctype']}")
# Expected: Purchase Invoice
print(f"Name: {result['name']}")
# Expected: ACC-PINV-YYYY-NNNNN or similar
print(f"URL: {result['url']}")
# Expected: /app/purchase-invoice/ACC-PINV-...
print(f"Warnings: {result['warnings']}")
print(f"Created masters: {result['created_masters']}")

# Verify the document exists and is Draft
created_doc = frappe.get_doc("Purchase Invoice", result["name"])
print(f"Status: {created_doc.docstatus}")
# Expected: 0 (Draft)
print(f"Supplier: {created_doc.supplier}")
# Expected: Wind Power LLC
print(f"Items: {len(created_doc.items)}")
# Expected: 2
assert created_doc.docstatus == 0, "Document should be Draft (docstatus=0)"
assert len(created_doc.items) == 2, f"Expected 2 items, got {len(created_doc.items)}"

print("End-to-end create_document test passed")

# Cleanup: delete the test document
frappe.delete_doc("Purchase Invoice", result["name"], force=True)
frappe.db.commit()
print("Cleanup done")
```

> **Note:** Adjust `test_supplier` and `company` to match records in your
> test site. This test creates and then deletes a Draft Purchase Invoice.

---

### Test 6.8 — create_document with auto-create masters

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import create_document

# Use names that definitely don't exist
test_supplier = "IDP-AutoTest-Supplier-Phase6"
test_item = "IDP-AutoTest-Item-Phase6"

# Ensure they don't exist
for dt, name in [("Supplier", test_supplier), ("Item", test_item)]:
    if frappe.db.exists(dt, name):
        frappe.delete_doc(dt, name, force=True)
frappe.db.commit()

company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": test_supplier,
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
    },
    items=[
        {"item_code": test_item, "item_name": test_item, "qty": 5, "rate": 200, "amount": 1000},
    ],
)

result = create_document(
    doc,
    company=company,
    create_missing_masters=True,
    skip_validation=True,
)
print(f"Success: {result['success']}")
# Expected: True
print(f"Created masters: {result['created_masters']}")
# Expected: [{"doctype": "Supplier", "name": "IDP-AutoTest-Supplier-Phase6"},
#             {"doctype": "Item", "name": "IDP-AutoTest-Item-Phase6"}]
assert result["success"]
assert len(result["created_masters"]) >= 1, "Expected at least 1 auto-created master"

# Verify supplier was auto-created
assert frappe.db.exists("Supplier", test_supplier), "Supplier was not auto-created"
assert frappe.db.exists("Item", test_item), "Item was not auto-created"
print("Auto-create masters during document creation test passed")

# Cleanup
frappe.delete_doc("Purchase Invoice", result["name"], force=True)
frappe.delete_doc("Supplier", test_supplier, force=True)
frappe.delete_doc("Item", test_item, force=True)
frappe.db.commit()
print("Cleanup done")
```

---

### Test 6.9 — Text field preservation

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.mappers.document_creator import create_document

test_supplier = "Wind Power LLC"
if not frappe.db.exists("Supplier", test_supplier):
    frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": test_supplier,
        "supplier_group": "All Supplier Groups",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

custom_remarks = "IDP extraction: Invoice from vendor, terms Net 30"
doc = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": test_supplier,
        "posting_date": "2026-04-01",
        "due_date": "2026-04-30",
        "remarks": custom_remarks,
    },
    items=[
        {"item_name": "Widget", "qty": 1, "rate": 500, "amount": 500},
    ],
)

result = create_document(doc, company=company, create_missing_masters=True, skip_validation=True)
created_doc = frappe.get_doc("Purchase Invoice", result["name"])
print(f"Remarks preserved: {created_doc.remarks == custom_remarks}")
print(f"Actual remarks: {repr(created_doc.remarks)}")
# Expected: Remarks preserved: True (if preservation worked)
# Note: ERPNext may auto-generate remarks; the preservation step re-applies ours

print("Text field preservation test passed")

# Cleanup
frappe.delete_doc("Purchase Invoice", result["name"], force=True)
frappe.db.commit()
print("Cleanup done")
```

---

## Phase 7: Document Comparison & Reconciliation

> **Important:** Phase 7 tests require existing ERPNext records.
> Tests 7.5–7.8 create temporary documents for comparison — clean up
> afterwards if needed. Run on a **test site only** (`test.local`).

### Test 7.1 — Data model imports

```python
from idp.idp.comparison import (
    ComparisonResult, FieldComparison, ItemComparison,
    compare_with_record, find_matching_record,
)

# ComparisonResult defaults
cr = ComparisonResult()
print(f"doctype: {repr(cr.doctype)}")         # Expected: ""
print(f"matches: {cr.matches}")               # Expected: []
print(f"discrepancies: {cr.discrepancies}")   # Expected: []
print(f"summary: {repr(cr.summary)}")         # Expected: ""

# FieldComparison
fc = FieldComparison(field="supplier", label="Supplier", document_value="Tara", record_value="Tara")
print(f"FC status: {fc.status}")              # Expected: match

# ItemComparison
ic = ItemComparison(item_code="ITEM-001", item_name="Widget A", status="match")
print(f"IC status: {ic.status}")              # Expected: match

print("Data model import tests passed")
```

---

### Test 7.2 — Type-aware value comparison (dates)

```python
from idp.idp.comparison import _compare_dates

# Same date, different formats
cmp = _compare_dates("posting_date", "Date", "2026-04-01", "2026-04-01")
print(f"Same date: {cmp.status}")
# Expected: match

# Different dates
cmp2 = _compare_dates("posting_date", "Date", "2026-04-01", "2026-04-15")
print(f"Different date: {cmp2.status}")
# Expected: mismatch
print(f"Diff: {cmp2.difference}")
# Expected: "Document: 2026-04-01, Record: 2026-04-15"

print("Date comparison tests passed")
```

---

### Test 7.3 — Type-aware value comparison (numbers)

```python
from idp.idp.comparison import _compare_numbers

# Equal within precision
cmp = _compare_numbers("grand_total", "Grand Total", 1000.004, 1000.006, 2)
print(f"Close numbers: {cmp.status}")
# Expected: match (both round to 1000.00)

# Mismatched
cmp2 = _compare_numbers("grand_total", "Grand Total", 1000.00, 990.00, 2)
print(f"Diff numbers: {cmp2.status}")
# Expected: mismatch
print(f"Diff: {cmp2.difference}")
# Expected: "Document: 1000.0, Record: 990.0 (diff: +10.00)"

# Integer comparison
cmp3 = _compare_numbers("qty", "Qty", 10, 10, 0)
print(f"Same int: {cmp3.status}")
# Expected: match

print("Number comparison tests passed")
```

---

### Test 7.4 — Type-aware value comparison (strings)

```python
from idp.idp.comparison import _compare_strings

# Case-insensitive match
cmp = _compare_strings("supplier", "Supplier", "Tara Technologies", "tara technologies")
print(f"Case-insensitive: {cmp.status}")
# Expected: match

# Whitespace-trimmed match
cmp2 = _compare_strings("supplier", "Supplier", "  Tara Tech  ", "Tara Tech")
print(f"Whitespace-trimmed: {cmp2.status}")
# Expected: match

# Mismatch
cmp3 = _compare_strings("supplier", "Supplier", "Tara Tech", "Wind Power")
print(f"Mismatch: {cmp3.status}")
# Expected: mismatch
print(f"Diff: {cmp3.difference}")
# Expected: 'Document: "Tara Tech", Record: "Wind Power"'

print("String comparison tests passed")
```

---

### Test 7.5 — compare_with_record: non-existent record

```python
from idp.idp.mappers.base import MappedDocument
from idp.idp.comparison import compare_with_record

doc = MappedDocument(
    doctype="Purchase Invoice",
    header={"supplier": "Test"},
    items=[],
)

result = compare_with_record(doc, "Purchase Invoice", "NONEXISTENT-PI-999")
print(f"Summary: {result.summary}")
# Expected: 'Purchase Invoice "NONEXISTENT-PI-999" does not exist'
assert "does not exist" in result.summary
print("Non-existent record test passed")
```

---

### Test 7.6 — compare_with_record: full comparison against real record

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.comparison import compare_with_record

# Create a test Purchase Invoice to compare against
test_supplier = "Wind Power LLC"
if not frappe.db.exists("Supplier", test_supplier):
    frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": test_supplier,
        "supplier_group": "All Supplier Groups",
    }).insert(ignore_permissions=True)

company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

pi = frappe.get_doc({
    "doctype": "Purchase Invoice",
    "supplier": test_supplier,
    "posting_date": "2026-04-01",
    "due_date": "2026-04-30",
    "company": company,
    "items": [
        {"item_name": "Widget A", "qty": 10, "rate": 100},
        {"item_name": "Widget B", "qty": 5, "rate": 200},
    ],
})
pi.flags.ignore_permissions = True
pi.insert()
frappe.db.commit()

# Now compare with extracted data that has some differences
extracted = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": test_supplier,
        "posting_date": "2026-04-01",     # same
        "due_date": "2026-05-15",         # different
    },
    items=[
        {"item_name": "Widget A", "qty": 10, "rate": 100},     # same
        {"item_name": "Widget B", "qty": 8, "rate": 200},      # qty differs
    ],
)

result = compare_with_record(extracted, "Purchase Invoice", pi.name)
print(f"Summary: {result.summary}")
print(f"Matches: {len(result.matches)}")
print(f"Discrepancies: {len(result.discrepancies)}")
for d in result.discrepancies:
    print(f"  [{d.status}] {d.label}: {d.difference}")
print(f"Items comparison: {len(result.items_comparison)}")
for ic in result.items_comparison:
    print(f"  {ic.item_name} [{ic.status}]")
    for fc in ic.field_comparisons:
        if fc.status == "mismatch":
            print(f"    {fc.label}: {fc.difference}")

# Expected:
#   posting_date: match
#   due_date: mismatch (2026-05-15 vs 2026-04-30)
#   Widget A: match
#   Widget B: partial_match (qty 8 vs 5)

assert len(result.discrepancies) >= 1, "Expected at least one discrepancy"
print("Full comparison test passed")

# Cleanup
frappe.delete_doc("Purchase Invoice", pi.name, force=True)
frappe.db.commit()
print("Cleanup done")
```

---

### Test 7.7 — find_matching_record: by reference

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.comparison import find_matching_record

# Create a PO to match against
test_supplier = "Wind Power LLC"
company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

po = frappe.get_doc({
    "doctype": "Purchase Order",
    "supplier": test_supplier,
    "transaction_date": "2026-04-01",
    "schedule_date": "2026-04-15",
    "company": company,
    "items": [
        {"item_name": "Widget A", "qty": 10, "rate": 100, "schedule_date": "2026-04-15"},
    ],
})
po.flags.ignore_permissions = True
po.insert()
frappe.db.commit()

# Try to find it by reference (using PO name as bill_no)
extracted = MappedDocument(
    doctype="Purchase Invoice",
    header={"bill_no": po.name, "supplier": test_supplier},
    items=[],
)

match = find_matching_record(extracted, "Purchase Order")
print(f"Found by reference: {match}")
# Expected: the PO name
assert match == po.name, f"Expected {po.name}, got {match}"
print("Reference matching test passed")

# Cleanup
frappe.delete_doc("Purchase Order", po.name, force=True)
frappe.db.commit()
print("Cleanup done")
```

---

### Test 7.8 — find_matching_record: by supplier + date + total

```python
import frappe
from idp.idp.mappers.base import MappedDocument
from idp.idp.comparison import find_matching_record

test_supplier = "Wind Power LLC"
company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

po = frappe.get_doc({
    "doctype": "Purchase Order",
    "supplier": test_supplier,
    "transaction_date": "2026-04-01",
    "schedule_date": "2026-04-15",
    "company": company,
    "items": [
        {"item_name": "Widget A", "qty": 10, "rate": 500, "schedule_date": "2026-04-15"},
    ],
})
po.flags.ignore_permissions = True
po.insert()
frappe.db.commit()

# Match by supplier + date + approximate total
extracted = MappedDocument(
    doctype="Purchase Invoice",
    header={
        "supplier": test_supplier,
        "posting_date": "2026-04-02",       # within 15 days
        "grand_total": po.grand_total,      # exact total match
    },
    items=[],
)

match = find_matching_record(extracted, "Purchase Order", company=company)
print(f"Found by supplier+date+total: {match}")
# Expected: the PO name (or None if multiple POs exist for this supplier)
if match:
    assert match == po.name, f"Expected {po.name}, got {match}"
    print("Supplier+date+total matching test passed")
else:
    print("No match found (may be due to other POs in the system)")

# Cleanup
frappe.delete_doc("Purchase Order", po.name, force=True)
frappe.db.commit()
print("Cleanup done")
```

---

### Test 7.9 — Item-level comparison details

```python
from idp.idp.comparison import _compare_single_item, FieldComparison

field_meta = {
    "item_name": {"fieldname": "item_name", "fieldtype": "Data", "label": "Item Name"},
    "qty": {"fieldname": "qty", "fieldtype": "Float", "label": "Qty"},
    "rate": {"fieldname": "rate", "fieldtype": "Currency", "label": "Rate"},
    "amount": {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount"},
}

# Mock record row (simulates a frappe doc row with .get())
class MockRow:
    def __init__(self, data):
        self._data = data
    def get(self, key):
        return self._data.get(key)

doc_row = {"item_name": "Widget A", "qty": 10, "rate": 100, "amount": 1000}
rec_row = MockRow({"item_name": "Widget A", "qty": 8, "rate": 100, "amount": 800})

result = _compare_single_item(doc_row, rec_row, field_meta)
print(f"Status: {result.status}")
# Expected: partial_match (qty and amount differ)
for fc in result.field_comparisons:
    print(f"  {fc.label}: {fc.status} {fc.difference or ''}")
# Expected:
#   Item Name: match
#   Qty: mismatch Document: 10.0, Record: 8.0 (diff: +2.000)
#   Rate: match
#   Amount: mismatch Document: 1000.0, Record: 800.0 (diff: +200.00)

mismatches = [fc for fc in result.field_comparisons if fc.status == "mismatch"]
assert len(mismatches) >= 1, "Expected at least one mismatch"
print("Item-level comparison test passed")
```

---

### Test 7.10 — Summary generation

```python
from idp.idp.comparison import ComparisonResult, FieldComparison, ItemComparison, _build_summary

result = ComparisonResult(
    doctype="Purchase Invoice",
    docname="PI-001",
    matches=[
        FieldComparison(field="supplier", label="Supplier", status="match"),
        FieldComparison(field="posting_date", label="Date", status="match"),
    ],
    discrepancies=[
        FieldComparison(field="grand_total", label="Grand Total", status="mismatch"),
    ],
    missing_in_document=["Tax Category (tax_category)"],
    missing_in_record=[],
    items_comparison=[
        ItemComparison(item_code="A", item_name="Widget A", status="match"),
        ItemComparison(item_code="B", item_name="Widget B", status="partial_match"),
    ],
)

summary = _build_summary(result)
print(f"Summary: {summary}")
# Expected: "2/3 header field(s) match; 1 discrepancy(ies): Grand Total; 1 field(s) only in record; Items: 1 match, 1 partial"
assert "2/3" in summary
assert "Grand Total" in summary
print("Summary generation test passed")
```

---

## Phase 8: HTTP API Endpoints

> **Important:** Phase 8 tests call `@frappe.whitelist()` API functions
> directly from `bench console`. Some tests create/delete records — run
> on a **test site only** (`test.local`).

### Test 8.1 — API module imports

```python
from idp.api.upload import upload_document
from idp.api.extract import extract_document
from idp.api.create import create_erp_document, get_missing_masters
from idp.api.compare import compare_document, find_matching_record
from idp.api.settings import get_settings

print("upload_document:", upload_document)
print("extract_document:", extract_document)
print("create_erp_document:", create_erp_document)
print("get_missing_masters:", get_missing_masters)
print("compare_document:", compare_document)
print("find_matching_record:", find_matching_record)
print("get_settings:", get_settings)
print("All API imports OK")
# Expected: All functions import without error
```

---

### Test 8.2 — get_settings returns expected structure

```python
from idp.api.settings import get_settings

result = get_settings()
print(f"enabled: {result['enabled']}")
# Expected: True (default)

print(f"supported_formats: {result['supported_formats']}")
# Expected: list of extensions like ['.csv', '.doc', '.jpeg', ...]

print(f"supported_doctypes: {result['supported_doctypes']}")
# Expected: list of 11 DocTypes

print(f"ocr_languages: {result['ocr_languages']}")
# Expected: {'en': 'English', 'ch': 'Chinese', ...}

print(f"max_file_size_mb: {result['max_file_size_mb']}")
# Expected: 25

print(f"default_target_doctype: {result['default_target_doctype']}")
# Expected: Purchase Invoice

print(f"features: {result['features']}")
# Expected: dict with keys: ocr, table_extraction, comparison, etc.

assert "supported_formats" in result
assert "supported_doctypes" in result
assert "features" in result
assert isinstance(result["features"], dict)
assert "ocr" in result["features"]
print("get_settings test passed")
```

---

### Test 8.3 — extract_document: input validation

```python
import frappe
from idp.api.extract import extract_document

# Missing file_url
try:
    extract_document(file_url="", target_doctype="Purchase Invoice")
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected empty file_url")

# Invalid DocType
try:
    extract_document(file_url="/private/files/test.pdf", target_doctype="Bogus DocType")
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected invalid DocType")

print("extract_document input validation test passed")
```

---

### Test 8.4 — extract_document: error handling for missing file

```python
from idp.api.extract import extract_document

# File that doesn't exist — should return success=False with error info
result = extract_document(
    file_url="/private/files/nonexistent-idp-test-file.pdf",
    target_doctype="Purchase Invoice",
)
print(f"success: {result['success']}")
# Expected: False
print(f"error_type: {result.get('error_type')}")
# Expected: ExtractionError
print(f"error: {result.get('error')}")
# Expected: "File not found on disk: ..."
print(f"processing_time_ms: {result.get('processing_time_ms')}")

assert result["success"] is False
assert "error" in result
print("extract_document error handling test passed")
```

---

### Test 8.5 — create_erp_document: input validation

```python
import frappe
from idp.api.create import create_erp_document

# Invalid DocType
try:
    create_erp_document(
        target_doctype="Bogus",
        extracted_data='{"header": {}, "items": []}',
    )
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected invalid DocType")

# Invalid JSON
try:
    create_erp_document(
        target_doctype="Purchase Invoice",
        extracted_data="not valid json {{{",
    )
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected invalid JSON")

print("create_erp_document input validation test passed")
```

---

### Test 8.6 — create_erp_document: missing master error path

```python
from idp.api.create import create_erp_document

result = create_erp_document(
    target_doctype="Purchase Invoice",
    extracted_data={
        "header": {
            "supplier": "ZZZ-API-Test-Nonexistent-Supplier",
            "posting_date": "2026-04-01",
            "due_date": "2026-04-30",
        },
        "items": [{"item_name": "Widget", "qty": 10, "rate": 100, "amount": 1000}],
    },
    create_missing_masters=False,
)
print(f"success: {result['success']}")
# Expected: False
print(f"error_type: {result.get('error_type')}")
# Expected: MissingMasterError
print(f"details: {result.get('details')}")
# Expected: {"missing": ["Supplier:ZZZ-API-Test-Nonexistent-Supplier"]}

assert result["success"] is False
assert result["error_type"] == "MissingMasterError"
print("Missing master error path test passed")
```

---

### Test 8.7 — create_erp_document: full end-to-end

```python
import frappe
from idp.api.create import create_erp_document

test_supplier = "Wind Power LLC"
if not frappe.db.exists("Supplier", test_supplier):
    frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": test_supplier,
        "supplier_group": "All Supplier Groups",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name", limit=1)[0]

result = create_erp_document(
    target_doctype="Purchase Invoice",
    extracted_data={
        "header": {
            "supplier": test_supplier,
            "posting_date": "2026-04-01",
            "due_date": "2026-04-30",
            "currency": "INR",
            "bill_no": "IDP-API-TEST-001",
        },
        "items": [
            {"item_name": "Widget A", "qty": 10, "rate": 100, "amount": 1000},
            {"item_name": "Widget B", "qty": 5, "rate": 200, "amount": 1000},
        ],
    },
    company=company,
    create_missing_masters=True,
)
print(f"success: {result['success']}")
# Expected: True
print(f"doctype: {result.get('doctype')}")
# Expected: Purchase Invoice
print(f"name: {result.get('name')}")
# Expected: ACC-PINV-... or similar
print(f"url: {result.get('url')}")
print(f"warnings: {result.get('warnings')}")
print(f"created_masters: {result.get('created_masters')}")

assert result["success"] is True
assert result["doctype"] == "Purchase Invoice"

# Cleanup
frappe.delete_doc("Purchase Invoice", result["name"], force=True)
frappe.db.commit()
print("End-to-end create via API test passed")
```

---

### Test 8.8 — get_missing_masters

```python
from idp.api.create import get_missing_masters

result = get_missing_masters(
    target_doctype="Purchase Invoice",
    extracted_data={
        "header": {"supplier": "ZZZ-Nonexistent-Supplier-API-Test"},
        "items": [
            {"item_code": "ZZZ-FAKE-ITEM-API-TEST", "qty": 1, "rate": 50, "amount": 50},
        ],
    },
)
print(f"missing count: {result['count']}")
# Expected: >= 2 (Supplier + Item)
print(f"missing: {result['missing']}")

assert result["count"] >= 1
assert any(m["doctype"] == "Supplier" for m in result["missing"])
print("get_missing_masters test passed")
```

---

### Test 8.9 — compare_document: input validation

```python
import frappe
from idp.api.compare import compare_document

# Missing file_url
try:
    compare_document(
        file_url="",
        compare_doctype="Purchase Invoice",
        compare_docname="PI-001",
    )
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected empty file_url")

# Missing docname
try:
    compare_document(
        file_url="/private/files/test.pdf",
        compare_doctype="Purchase Invoice",
        compare_docname="",
    )
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected empty docname")

# Invalid DocType
try:
    compare_document(
        file_url="/private/files/test.pdf",
        compare_doctype="Bogus",
        compare_docname="PI-001",
    )
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected invalid DocType")

print("compare_document input validation test passed")
```

---

### Test 8.10 — find_matching_record: input validation and error handling

```python
import frappe
from idp.api.compare import find_matching_record

# Missing file_url
try:
    find_matching_record(file_url="", target_doctype="Purchase Order")
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected empty file_url")

# Invalid DocType
try:
    find_matching_record(file_url="/private/files/test.pdf", target_doctype="Bogus")
    print("ERROR: Should have thrown")
except frappe.ValidationError:
    print("Correctly rejected invalid DocType")

# Non-existent file — should return found=False gracefully
result = find_matching_record(
    file_url="/private/files/nonexistent-idp-match-test.pdf",
    target_doctype="Purchase Order",
)
print(f"found: {result.get('found')}")
# Expected: False
print(f"error_type: {result.get('error_type')}")
# Expected: ExtractionError (file not found)

assert result["found"] is False
print("find_matching_record error handling test passed")
```

---

### Test 8.11 — JSON string parameter parsing

```python
import json
from idp.api.create import _parse_json_param

# Valid JSON string
result = _parse_json_param('{"supplier": "Tara Tech"}', "test")
print(f"Parsed: {result}")
# Expected: {"supplier": "Tara Tech"}
assert result == {"supplier": "Tara Tech"}

# Already a dict — pass through
result2 = _parse_json_param({"a": 1}, "test")
print(f"Dict passthrough: {result2}")
# Expected: {"a": 1}
assert result2 == {"a": 1}

# Already a list — pass through
result3 = _parse_json_param([1, 2, 3], "test")
print(f"List passthrough: {result3}")
# Expected: [1, 2, 3]
assert result3 == [1, 2, 3]

print("JSON parameter parsing test passed")
```

---

### Test 8.12 — Comparison serialization

```python
from idp.idp.comparison import ComparisonResult, FieldComparison, ItemComparison
from idp.api.compare import _serialize_comparison

result = ComparisonResult(
    doctype="Purchase Invoice",
    docname="PI-001",
    matches=[
        FieldComparison(field="supplier", label="Supplier", status="match",
                       document_value="Tara", record_value="Tara"),
    ],
    discrepancies=[
        FieldComparison(field="grand_total", label="Grand Total", status="mismatch",
                       document_value=1000, record_value=990, difference="Document: 1000, Record: 990"),
    ],
    missing_in_document=["tax_category"],
    missing_in_record=[],
    items_comparison=[
        ItemComparison(item_code="A", item_name="Widget A", status="match", field_comparisons=[]),
    ],
    summary="1/2 match",
)

serialized = _serialize_comparison(result)
print(f"doctype: {serialized['doctype']}")
# Expected: Purchase Invoice
print(f"matches: {len(serialized['matches'])}")
# Expected: 1
print(f"discrepancies: {len(serialized['discrepancies'])}")
# Expected: 1
print(f"items_comparison: {len(serialized['items_comparison'])}")
# Expected: 1
print(f"summary: {serialized['summary']}")
# Expected: 1/2 match

assert serialized["matches"][0]["field"] == "supplier"
assert serialized["discrepancies"][0]["field"] == "grand_total"
assert serialized["items_comparison"][0]["item_code"] == "A"
print("Comparison serialization test passed")
```

---

## Phase 9: Frontend -- Vue 3 SPA with Frappe UI

> **Note:** Phase 9 delivers the frontend source files. These tests verify
> the file structure, build configuration, and Python SPA entry point.
> The Vue components themselves are tested via `yarn dev` / `yarn build`.

### Test 9.1 — Frontend directory structure

```bash
# Run from the project root
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp

# Verify all expected files exist
for f in \
  frontend/package.json \
  frontend/vite.config.js \
  frontend/tailwind.config.js \
  frontend/postcss.config.js \
  frontend/index.html \
  frontend/src/main.js \
  frontend/src/App.vue \
  frontend/src/router.js \
  frontend/src/index.css \
  frontend/src/utils/api.js \
  frontend/src/utils/formatters.js \
  frontend/src/composables/useSettings.js \
  frontend/src/composables/useFileUpload.js \
  frontend/src/composables/useExtraction.js \
  frontend/src/composables/useComparison.js \
  frontend/src/components/FileDropzone.vue \
  frontend/src/components/ExtractionForm.vue \
  frontend/src/components/ExtractionPreview.vue \
  frontend/src/components/ComparisonTable.vue \
  frontend/src/components/ConfirmationCard.vue \
  frontend/src/components/MissingMastersDialog.vue \
  frontend/src/components/ProcessingStatus.vue \
  frontend/src/components/DocumentThumbnail.vue \
  frontend/src/components/SettingsPanel.vue \
  frontend/src/components/StatusBadge.vue \
  frontend/src/pages/DocumentUpload.vue \
  frontend/src/pages/ExtractionReview.vue \
  frontend/src/pages/ComparisonView.vue \
  frontend/src/pages/ProcessingHistory.vue \
  idp/www/idp.py; do
  if [ -f "$f" ]; then
    echo "OK: $f"
  else
    echo "MISSING: $f"
  fi
done

# Expected: all files show "OK"
```

---

### Test 9.2 — package.json structure

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp/frontend

# Verify key fields
python3 -c "
import json
with open('package.json') as f:
    pkg = json.load(f)

assert pkg['name'] == 'idp-frontend', f'name: {pkg[\"name\"]}'
assert 'vue' in pkg['dependencies'], 'Missing vue dependency'
assert 'vue-router' in pkg['dependencies'], 'Missing vue-router'
assert 'frappe-ui' in pkg['dependencies'], 'Missing frappe-ui'
assert 'pinia' in pkg['dependencies'], 'Missing pinia'
assert 'build' in pkg['scripts'], 'Missing build script'
assert '/assets/idp/frontend/' in pkg['scripts']['build'], 'Build base mismatch'
assert 'copy-html-entry' in pkg['scripts'], 'Missing copy-html-entry script'
print('package.json structure test passed')
"
```

---

### Test 9.3 — www/idp.py context provider

```python
from idp.www.idp import get_boot, no_cache

# Verify no_cache is set
assert no_cache == 1, f"no_cache should be 1, got {no_cache}"

# Verify boot data structure
boot = get_boot()
print(f"site_name: {boot.site_name}")
print(f"user: {boot.user}")
print(f"desk_theme: {boot.desk_theme}")
print(f"timezone: {boot.timezone}")
assert "site_name" in boot, "Missing site_name"
assert "csrf_token" in boot, "Missing csrf_token"
assert "user" in boot, "Missing user"
assert "desk_theme" in boot, "Missing desk_theme"
assert "timezone" in boot, "Missing timezone"
print("www/idp.py context provider test passed")
```

---

### Test 9.4 — Router configuration matches hooks.py

```python
# Verify that hooks.py website_route_rules match the Vue router base
import idp.hooks as hooks

rules = hooks.website_route_rules
assert len(rules) >= 1, "No website_route_rules found"

idp_rule = rules[0]
assert idp_rule["from_route"] == "/idp/<path:app_path>", f"Unexpected route: {idp_rule}"
assert idp_rule["to_route"] == "idp", f"Unexpected to_route: {idp_rule}"

# The Vue router should use createWebHistory('/idp/')
# This is verified in the router.js file
print("Route configuration test passed")
```

---

### Test 9.5 — API utility functions exist

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp/frontend

# Check that api.js exports the expected functions
python3 -c "
content = open('src/utils/api.js').read()
expected = [
    'fetchSettings', 'uploadDocument', 'extractDocument',
    'createDocument', 'getMissingMasters',
    'compareDocument', 'findMatchingRecord',
]
for fn in expected:
    assert f'export function {fn}' in content, f'Missing export: {fn}'
    print(f'OK: {fn}')
print('API utility functions test passed')
"
```

---

### Test 9.6 — Formatter utility functions exist

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp/frontend

python3 -c "
content = open('src/utils/formatters.js').read()
expected = [
    'formatNumber', 'formatCurrency', 'formatDate',
    'timeAgo', 'formatFileSize', 'formatConfidence',
]
for fn in expected:
    assert f'export function {fn}' in content, f'Missing export: {fn}'
    print(f'OK: {fn}')
print('Formatter utility functions test passed')
"
```

---

### Test 9.7 — Vue page components have correct structure

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp/frontend

python3 -c "
import os

pages = [
    'src/pages/DocumentUpload.vue',
    'src/pages/ExtractionReview.vue',
    'src/pages/ComparisonView.vue',
    'src/pages/ProcessingHistory.vue',
]
for page in pages:
    content = open(page).read()
    assert '<template>' in content, f'{page}: Missing <template>'
    assert 'Copyright (c) 2026' in content, f'{page}: Missing copyright header'
    print(f'OK: {page}')
print('Vue page structure test passed')
"
```

---

### Test 9.8 — Composables have correct exports

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp/frontend

python3 -c "
composables = {
    'src/composables/useSettings.js': 'useSettings',
    'src/composables/useFileUpload.js': 'useFileUpload',
    'src/composables/useExtraction.js': 'useExtraction',
    'src/composables/useComparison.js': 'useComparison',
}
for path, fn in composables.items():
    content = open(path).read()
    assert f'export function {fn}' in content, f'{path}: Missing export {fn}'
    print(f'OK: {fn}')
print('Composables export test passed')
"
```

---

## Phase 11: DocTypes, Workspace & Settings

> **Important:** Phase 11 tests verify that the DocTypes, workspace,
> and permission hooks installed by the app can be loaded and behave
> correctly.  Run on a **test site only** (`test.local`).

### Test 11.1 — DocType JSON files load

```python
import json, os
from pathlib import Path

APP = Path("apps/idp/idp/idp/doctype")
expected = {
    "idp_settings": "IDP Settings",
    "idp_document_log": "IDP Document Log",
    "idp_extraction_template": "IDP Extraction Template",
}
for folder, doctype_name in expected.items():
    path = APP / folder / f"{folder}.json"
    assert path.exists(), f"Missing JSON: {path}"
    data = json.loads(path.read_text())
    assert data["name"] == doctype_name, f"{path}: name mismatch"
    assert data["module"] == "IDP"
    print(f"OK: {doctype_name}")
print("Phase 11 DocType JSON test passed")
# Expected: prints OK for each DocType and the final pass line
```

---

### Test 11.2 — IDP Settings single DocType exists and defaults load

```python
import frappe
from idp.core.config import get_idp_settings, is_feature_enabled, get_confidence_threshold

settings = get_idp_settings()
assert "enabled" in settings
assert "default_ocr_language" in settings
assert "confidence_threshold" in settings

print(f"enabled: {settings.get('enabled')}")
print(f"default_ocr_language: {settings.get('default_ocr_language')}")
print(f"confidence_threshold: {settings.get('confidence_threshold')}")
# Expected: enabled=1, default_ocr_language='en', confidence_threshold=0.70

print(f"is_feature_enabled('enable_comparison'): {is_feature_enabled('enable_comparison')}")
# Expected: True

print(f"get_confidence_threshold(): {get_confidence_threshold()}")
# Expected: 0.7

print("IDP Settings single DocType test passed")
```

---

### Test 11.3 — IDP Settings validation rejects out-of-range values

```python
import frappe
from idp.idp.doctype.idp_settings.idp_settings import IDPSettings

doc = frappe.get_single("IDP Settings")
doc.confidence_threshold = 1.5
try:
    doc.validate()
    print("ERROR: Should have thrown")
except frappe.ValidationError as e:
    print(f"Correctly rejected out-of-range threshold: {e}")

doc.confidence_threshold = 0.7  # reset
doc.max_file_size_mb = 0
try:
    doc.validate()
    print("ERROR: Should have thrown")
except frappe.ValidationError as e:
    print(f"Correctly rejected zero max_file_size_mb: {e}")

print("IDP Settings validation test passed")
# Expected: both out-of-range inputs raise ValidationError
```

---

### Test 11.4 — IDP Document Log insert + default user

```python
import frappe

doc = frappe.new_doc("IDP Document Log")
doc.file_url = "/private/files/phase11-test.pdf"
doc.file_name = "phase11-test.pdf"
doc.mime_type = "application/pdf"
doc.status = "Uploaded"
doc.insert(ignore_permissions=True)

assert doc.user == frappe.session.user, "user should auto-default to session user"
print(f"created log row: {doc.name}, user={doc.user}, status={doc.status}")

# cleanup
frappe.delete_doc("IDP Document Log", doc.name, ignore_permissions=True)
print("IDP Document Log test passed")
# Expected: row inserts, user defaults to Administrator (or current session user)
```

---

### Test 11.5 — IDP Extraction Template JSON validation

```python
import frappe

doc = frappe.new_doc("IDP Extraction Template")
doc.template_name = "Phase11 Test Template"
doc.target_doctype = "Purchase Invoice"
doc.field_mappings = "{ invalid json"
try:
    doc.validate()
    print("ERROR: Should have thrown")
except frappe.ValidationError as e:
    print(f"Correctly rejected invalid JSON: {e}")

# fix and retry
doc.field_mappings = '{"invoice_number": "bill_no"}'
doc.validate()
print("Valid JSON accepted")

print("IDP Extraction Template validation test passed")
# Expected: invalid JSON is rejected, valid JSON accepted
```

---

### Test 11.6 — Workspace JSON loads and references expected DocTypes

```python
import json
from pathlib import Path

path = Path("apps/idp/idp/idp/workspace/idp/idp.json")
assert path.exists(), f"Missing workspace: {path}"
ws = json.loads(path.read_text())

assert ws["name"] == "IDP"
assert ws["module"] == "IDP"
assert ws["public"] == 1

link_targets = {l.get("link_to") for l in ws.get("links", []) if l.get("type") == "Link"}
for expected in ("IDP Settings", "IDP Document Log", "IDP Conversation",
                 "IDP Message", "IDP Extraction Template"):
    assert expected in link_targets, f"Workspace missing link to {expected}"
    print(f"OK: workspace links to {expected}")

shortcut_labels = {s.get("label") for s in ws.get("shortcuts", [])}
assert "Upload Document" in shortcut_labels
assert "IDP Settings" in shortcut_labels
assert "Processing History" in shortcut_labels
print("Phase 11 Workspace test passed")
```

---

### Test 11.7 — add_to_apps_screen hook includes permission check

```python
from idp.hooks import add_to_apps_screen
entry = add_to_apps_screen[0]
print(f"name: {entry['name']}")
print(f"route: {entry['route']}")
print(f"has_permission: {entry.get('has_permission')}")
assert entry["name"] == "idp"
assert entry["route"] == "/idp"
assert entry.get("has_permission") == "idp.api.permissions.has_app_permission"
print("Phase 11 app entry test passed")
# Expected: has_permission resolves to idp.api.permissions.has_app_permission
```

---

### Test 11.8 — has_app_permission gates guest users

```python
import frappe
from idp.api.permissions import has_app_permission

original = frappe.session.user
try:
    frappe.set_user("Guest")
    assert has_app_permission() is False, "Guest should be denied"
    print("Guest denied: OK")

    frappe.set_user("Administrator")
    assert has_app_permission() is True, "Administrator should be allowed"
    print("Administrator allowed: OK")
finally:
    frappe.set_user(original)
print("has_app_permission test passed")
```

---

### Test 11.9 — IDP User role is created by after_install

```python
import frappe
from idp.install import _ensure_idp_user_role

_ensure_idp_user_role()  # idempotent
assert frappe.db.exists("Role", "IDP User"), "IDP User role should exist"
print("IDP User role exists")
# Expected: the role exists in the tabRole table
print("after_install IDP User role test passed")
```

---

## Phase 17: Conversation DocTypes (IDP Conversation, IDP Message)

> **Important:** Phase 17 tests create and delete conversation/message
> records.  Run on a **test site only** (`test.local`).

### Test 17.1 — Conversation DocType files load

```python
import json
from pathlib import Path

APP = Path("apps/idp/idp/idp/doctype")
expected = {
    "idp_conversation": ("IDP Conversation", False),
    "idp_conversation_attachment": ("IDP Conversation Attachment", True),
    "idp_message": ("IDP Message", False),
}
for folder, (name, istable) in expected.items():
    path = APP / folder / f"{folder}.json"
    data = json.loads(path.read_text())
    assert data["name"] == name, f"{path}: name mismatch"
    assert data["module"] == "IDP"
    if istable:
        assert data.get("istable") == 1, f"{name} should be istable=1"
    print(f"OK: {name}")
print("Phase 17 DocType JSON test passed")
```

---

### Test 17.2 — Create conversation via API

```python
import frappe
from idp.api.conversation import create_conversation, get_conversation

result = create_conversation(
    title="Phase 17 Test Conversation",
    target_doctype="Purchase Invoice",
    llm_provider="anthropic",
    llm_model="claude-opus-4-5-20251101",
    output_language="English",
)
print(f"created: {result}")
assert result["conversation_id"].startswith("IDPCONV-")
assert result["title"] == "Phase 17 Test Conversation"
assert result["status"] == "Active"

fetched = get_conversation(result["conversation_id"])
assert fetched["user"] == frappe.session.user
assert fetched["target_doctype"] == "Purchase Invoice"
assert fetched["llm_provider"] == "anthropic"
assert fetched["messages"] == []
print("create_conversation + get_conversation test passed")

# cleanup
frappe.delete_doc("IDP Conversation", result["conversation_id"], ignore_permissions=True)
```

---

### Test 17.3 — post_message appends messages in order

```python
import frappe
from idp.api.conversation import create_conversation, post_message, get_conversation

conv = create_conversation(title="Sequence test")
cid = conv["conversation_id"]

m1 = post_message(cid, content="First question", role="user")
m2 = post_message(cid, content="Assistant reply", role="assistant")
m3 = post_message(cid, content="Second question", role="user")

assert m1["sequence"] == 0
assert m2["sequence"] == 1
assert m3["sequence"] == 2
print(f"sequences: {m1['sequence']}, {m2['sequence']}, {m3['sequence']}")

# Fetch and verify ordering
fetched = get_conversation(cid)
seqs = [m["sequence"] for m in fetched["messages"]]
assert seqs == [0, 1, 2]
print(f"fetched sequences: {seqs}")
print(f"message_count: {fetched['message_count']}")
# Expected: 3
assert fetched["message_count"] == 3

# cleanup
for m in fetched["messages"]:
    frappe.delete_doc("IDP Message", m["name"], ignore_permissions=True)
frappe.delete_doc("IDP Conversation", cid, ignore_permissions=True)
print("post_message ordering test passed")
```

---

### Test 17.4 — Invalid role is rejected

```python
import frappe

conv = frappe.new_doc("IDP Conversation")
conv.user = frappe.session.user
conv.title = "Invalid role test"
conv.insert(ignore_permissions=True)

msg = frappe.new_doc("IDP Message")
msg.conversation = conv.name
msg.role = "attacker"  # invalid
msg.content = "should fail"
try:
    msg.insert(ignore_permissions=True)
    print("ERROR: Should have thrown")
except frappe.ValidationError as e:
    print(f"Correctly rejected invalid role: {e}")

frappe.delete_doc("IDP Conversation", conv.name, ignore_permissions=True)
print("IDP Message invalid role test passed")
# Expected: ValidationError raised for role='attacker'
```

---

### Test 17.5 — post_message auto-generates conversation title from first user message

```python
import frappe
from idp.api.conversation import create_conversation, post_message, get_conversation

# Create without title — controller gives a default "Conversation — ..." title
conv = create_conversation()
cid = conv["conversation_id"]
initial_title = conv["title"]
assert initial_title.startswith("Conversation —"), f"unexpected default: {initial_title}"

post_message(cid, content="Please extract this invoice", role="user")
fetched = get_conversation(cid)
assert fetched["title"] == "Please extract this invoice"
print(f"auto title: {fetched['title']}")

# cleanup
for m in fetched["messages"]:
    frappe.delete_doc("IDP Message", m["name"], ignore_permissions=True)
frappe.delete_doc("IDP Conversation", cid, ignore_permissions=True)
print("Auto-title generation test passed")
```

---

### Test 17.6 — archive_conversation sets status but preserves messages

```python
import frappe
from idp.api.conversation import (
    create_conversation, post_message, archive_conversation, get_conversation,
)

conv = create_conversation(title="Archive test")
cid = conv["conversation_id"]
post_message(cid, content="Hello", role="user")

result = archive_conversation(cid)
assert result["status"] == "Archived"
print(f"archived: {result}")

# messages still accessible
fetched = get_conversation(cid)
assert fetched["status"] == "Archived"
assert len(fetched["messages"]) == 1
print(f"archived conversation still has {len(fetched['messages'])} message(s)")

# cleanup
for m in fetched["messages"]:
    frappe.delete_doc("IDP Message", m["name"], ignore_permissions=True)
frappe.delete_doc("IDP Conversation", cid, ignore_permissions=True)
print("archive_conversation test passed")
```

---

### Test 17.7 — Conversation.add_attachment with file_id alias dedup

```python
import frappe

doc = frappe.new_doc("IDP Conversation")
doc.user = frappe.session.user
doc.title = "Attachment dedup test"
doc.insert(ignore_permissions=True)

doc.add_attachment(
    file_url="/private/files/invoice.pdf",
    file_name="invoice.pdf",
    mime_type="application/pdf",
    file_id="file_1",
    file_size=12345,
    inline_text_preview="TAX INVOICE ...",
)
# Duplicate by file_id — should be skipped
doc.add_attachment(
    file_url="/private/files/invoice.pdf",
    file_name="invoice.pdf",
    mime_type="application/pdf",
    file_id="file_1",
)
# New alias
doc.add_attachment(
    file_url="/private/files/po.pdf",
    file_name="po.pdf",
    mime_type="application/pdf",
    file_id="file_2",
)
doc.save(ignore_permissions=True)

aliases = [a.file_id for a in doc.attachments]
print(f"aliases: {aliases}")
assert aliases == ["file_1", "file_2"], f"expected dedup, got {aliases}"

frappe.delete_doc("IDP Conversation", doc.name, ignore_permissions=True)
print("add_attachment dedup test passed")
# Expected: aliases == ['file_1', 'file_2'] (duplicate skipped)
```

---

### Test 17.8 — list_conversations filters by status

```python
import frappe
from idp.api.conversation import create_conversation, list_conversations, archive_conversation

c1 = create_conversation(title="Active one")
c2 = create_conversation(title="To archive")
archive_conversation(c2["conversation_id"])

active = list_conversations(status="Active", limit=10)
archived = list_conversations(status="Archived", limit=10)

active_titles = {r["title"] for r in active}
archived_titles = {r["title"] for r in archived}
print(f"active titles include 'Active one': {'Active one' in active_titles}")
print(f"archived titles include 'To archive': {'To archive' in archived_titles}")
assert "Active one" in active_titles
assert "To archive" in archived_titles
assert "To archive" not in active_titles

# cleanup
frappe.delete_doc("IDP Conversation", c1["conversation_id"], ignore_permissions=True)
frappe.delete_doc("IDP Conversation", c2["conversation_id"], ignore_permissions=True)
print("list_conversations filter test passed")
```

---

### Test 17.9 — get_permission_query_conditions scoping

```python
import frappe
from idp.idp.doctype.idp_conversation.idp_conversation import (
    get_permission_query_conditions as conv_cond,
)
from idp.idp.doctype.idp_message.idp_message import (
    get_permission_query_conditions as msg_cond,
)

# Administrator / System Manager -> empty string (no restriction)
assert conv_cond("Administrator") == ""
assert msg_cond("Administrator") == ""
print("Administrator has no restriction: OK")

# Regular user -> restriction referencing the user
cond = conv_cond("test.user@example.com")
assert "tabIDP Conversation" in cond
assert "test.user@example.com" in cond
print(f"conversation restriction: {cond}")

cond = msg_cond("test.user@example.com")
assert "tabIDP Message" in cond
assert "tabIDP Conversation" in cond
print(f"message restriction: {cond}")
print("permission query conditions test passed")
```

---

### Test 17.10 — post_message rejects unauthenticated access

```python
import frappe
from idp.api.conversation import create_conversation, post_message

conv = create_conversation(title="Auth test")
cid = conv["conversation_id"]

original = frappe.session.user
try:
    frappe.set_user("Guest")
    try:
        post_message(cid, content="guest attempt")
        print("ERROR: Guest should have been rejected")
    except (frappe.AuthenticationError, frappe.PermissionError) as e:
        print(f"Guest correctly rejected: {type(e).__name__}")
finally:
    frappe.set_user(original)

# cleanup
frappe.delete_doc("IDP Conversation", cid, ignore_permissions=True)
print("Guest auth test passed")
```

---

### Test 17.11 — has_conversation_permission respects ownership

```python
import frappe
from idp.api.permissions import has_conversation_permission

doc = frappe.new_doc("IDP Conversation")
doc.user = "alice@example.com"
doc.title = "Alice conv"
# Simulate without inserting — controller fields are enough for the hook
class _Stub:
    user = "alice@example.com"
    owner = "alice@example.com"

stub = _Stub()
assert has_conversation_permission(stub, user="alice@example.com") is True
assert has_conversation_permission(stub, user="bob@example.com") is False
assert has_conversation_permission(stub, user="Administrator") is True
print("has_conversation_permission ownership test passed")
```

---

## Phase 12: Bank Statement Processing

> **Note:** Phase 12 adds a specialised bank-statement extractor
> (`idp.idp.extractors.bank_statement`) and a reconciliation engine
> (`idp.idp.bank_reconciliation`) plus two whitelisted API endpoints
> in `idp.api.extract`. The tests below cover the pure-Python helpers,
> the reconciliation matching logic, the API wrappers, and the
> frontend wiring.

### Test 12.1 — Module imports

```python
from idp.idp.extractors.bank_statement import (
    BankStatement, BankStatementIssue, BankTransaction,
    extract_bank_statement, parse_bank_statement,
    statement_to_dict, transactions_from_dicts,
)
from idp.idp.bank_reconciliation import (
    ReconciliationMatch, ReconciledTransaction, ReconciliationResult,
    reconcile_bank_statement, result_to_dict,
)
from idp.api.extract import (
    extract_bank_statement_api, reconcile_bank_statement_api,
)
print("Phase 12 imports OK")
# Expected: Phase 12 imports OK
```

---

### Test 12.2 — Amount parsing (CR/DR, parens, grouping)

```python
from idp.idp.extractors.bank_statement import _parse_amount

assert _parse_amount("1,234.56") == 1234.56
assert _parse_amount("1,23,456.78") == 123456.78   # Indian grouping
assert _parse_amount("1.234,56") == 1234.56        # European
assert _parse_amount("(123.45)") == -123.45        # parenthesised negative
assert _parse_amount("500.00 CR") == 500.00
assert _parse_amount("500.00 DR") == -500.00
assert _parse_amount("") is None
assert _parse_amount(None) is None
assert _parse_amount("--") is None
print("Amount parsing test passed")
# Expected: Amount parsing test passed
```

---

### Test 12.3 — Date parsing (multiple formats, 2-digit years)

```python
from idp.idp.extractors.bank_statement import _parse_date

assert _parse_date("2026-01-15") == "2026-01-15"
assert _parse_date("15-01-2026") == "2026-01-15"
assert _parse_date("15/01/2026") == "2026-01-15"
assert _parse_date("15-Jan-2026") == "2026-01-15"
assert _parse_date("15-Jan-26") == "2026-01-15"   # 2-digit year coerced to 2000s
assert _parse_date("not a date") is None
assert _parse_date("") is None
print("Date parsing test passed")
# Expected: Date parsing test passed
```

---

### Test 12.4 — Header matching (English + substring)

```python
from idp.idp.extractors.bank_statement import (
    _match_header, _DATE_KEYWORDS, _DEBIT_KEYWORDS,
    _CREDIT_KEYWORDS, _BALANCE_KEYWORDS, _REFERENCE_KEYWORDS,
)

headers = [
    "Txn Date", "Narration", "Withdrawal (Dr)",
    "Deposit (Cr)", "Closing Balance (INR)", "Cheque No",
]
assert _match_header(headers, _DATE_KEYWORDS) == 0
assert _match_header(headers, _DEBIT_KEYWORDS) == 2
assert _match_header(headers, _CREDIT_KEYWORDS) == 3
assert _match_header(headers, _BALANCE_KEYWORDS) == 4
assert _match_header(headers, _REFERENCE_KEYWORDS) == 5
print("Header matching test passed")
# Expected: Header matching test passed
```

---

### Test 12.5 — parse_bank_statement on synthetic ExtractionResult

```python
from idp.idp.extractors.base import ExtractionResult
from idp.idp.extractors.bank_statement import parse_bank_statement

table = [
    ["Date", "Narration", "Debit", "Credit", "Balance"],
    ["2026-01-01", "Opening Entry", "", "", "1000.00"],
    ["2026-01-02", "ATM Withdrawal", "200.00", "", "800.00"],
    ["2026-01-03", "Salary", "", "5000.00", "5800.00"],
    ["2026-01-04", "UPI Payment", "150.00", "", "5650.00"],
]
er = ExtractionResult(text="Account No: 1234567890 INR", tables=[table], metadata={})
stmt = parse_bank_statement(er)

assert len(stmt.transactions) == 4
assert stmt.transactions[1].debit == 200.00
assert stmt.transactions[2].credit == 5000.00
assert stmt.closing_balance == 5650.00
assert stmt.currency == "INR"
assert stmt.account_number and "1234567890" in stmt.account_number
# No balance mismatch issues expected
errors = [i for i in stmt.issues if i.severity == "error"]
assert not errors, f"Unexpected errors: {errors}"
print(f"parse_bank_statement OK | txns={len(stmt.transactions)} "
      f"closing={stmt.closing_balance} issues={len(stmt.issues)}")
# Expected: parse_bank_statement OK | txns=4 closing=5650.0 issues=0
```

---

### Test 12.6 — parse_bank_statement flags running-balance mismatch

```python
from idp.idp.extractors.base import ExtractionResult
from idp.idp.extractors.bank_statement import parse_bank_statement

# Balance walk is broken: 1000 - 200 should be 800 but statement says 900
table = [
    ["Date", "Narration", "Debit", "Credit", "Balance"],
    ["2026-01-01", "Open", "", "", "1000.00"],
    ["2026-01-02", "Withdrawal", "200.00", "", "900.00"],
]
er = ExtractionResult(text="", tables=[table], metadata={})
stmt = parse_bank_statement(er)
warns = [i for i in stmt.issues if i.severity == "warning"]
assert any("balance mismatch" in w.message.lower() for w in warns), warns
print(f"Balance mismatch flagged | {warns[0].message}")
# Expected: Balance mismatch flagged | Running balance mismatch at row ...
```

---

### Test 12.7 — parse_bank_statement raises when no table present

```python
from idp.idp.extractors.base import ExtractionResult
from idp.idp.extractors.bank_statement import parse_bank_statement
from idp.core.exceptions import ExtractionError

er = ExtractionResult(text="No tables here", tables=[], metadata={})
try:
    parse_bank_statement(er)
    raise AssertionError("Expected ExtractionError")
except ExtractionError as exc:
    print(f"Correctly raised: {exc}")
# Expected: Correctly raised: Could not identify a transaction table in the document.
```

---

### Test 12.8 — statement_to_dict + transactions_from_dicts round-trip

```python
from idp.idp.extractors.base import ExtractionResult
from idp.idp.extractors.bank_statement import (
    parse_bank_statement, statement_to_dict, transactions_from_dicts,
)

table = [
    ["Date", "Narration", "Debit", "Credit", "Balance"],
    ["2026-01-02", "Payment", "100.00", "", "900.00"],
    ["2026-01-03", "Receipt", "", "250.00", "1150.00"],
]
stmt = parse_bank_statement(ExtractionResult(text="", tables=[table], metadata={}))
payload = statement_to_dict(stmt)
assert payload["transaction_count"] == 2
assert payload["transactions"][0]["debit"] == 100.00

round_trip = transactions_from_dicts(payload["transactions"])
assert len(round_trip) == 2
assert round_trip[0].debit == 100.00
assert round_trip[1].credit == 250.00
print("Round-trip test passed")
# Expected: Round-trip test passed
```

---

### Test 12.9 — reconcile_bank_statement with injected candidates (exact match)

```python
from idp.idp.extractors.bank_statement import BankTransaction
from idp.idp.bank_reconciliation import (
    ReconciliationMatch, reconcile_bank_statement,
)

txns = [
    BankTransaction(date="2026-01-10", description="Vendor A",
                    debit=500.00, credit=None, balance=9500.00,
                    reference="UTR123", row_index=1),
    BankTransaction(date="2026-01-12", description="Customer B",
                    debit=None, credit=1200.00, balance=10700.00,
                    reference=None, row_index=2),
]
candidates = [
    ReconciliationMatch(doctype="Payment Entry", name="PE-001",
                        posting_date="2026-01-10", amount=-500.00,
                        reference_no="UTR123", party="Vendor A"),
    ReconciliationMatch(doctype="Payment Entry", name="PE-002",
                        posting_date="2026-01-11", amount=1200.00,
                        reference_no=None, party="Customer B"),
]
result = reconcile_bank_statement(
    transactions=txns, bank_account="Bank - MEL",
    candidates=candidates,
)
assert len(result.matched) == 2, result.summary
assert result.matched[0].selected.match_type == "reference"
assert result.matched[1].selected.match_type == "exact"
assert not result.unmatched
print(f"Exact match reconciliation OK | {result.summary}")
# Expected: Exact match reconciliation OK | 2 matched (100.0% exact), 0 partial, ...
```

---

### Test 12.10 — reconcile flags partial and unmatched

```python
from idp.idp.extractors.bank_statement import BankTransaction
from idp.idp.bank_reconciliation import (
    ReconciliationMatch, reconcile_bank_statement,
)

txns = [
    BankTransaction(date="2026-01-10", description="Supplier X",
                    debit=300.00, credit=None, balance=0.0,
                    reference=None, row_index=1),
    BankTransaction(date="2026-01-11", description="Orphan",
                    debit=None, credit=999.00, balance=0.0,
                    reference=None, row_index=2),
]
candidates = [
    # Amount matches but date is 10 days off -> "partial"
    ReconciliationMatch(doctype="Payment Entry", name="PE-010",
                        posting_date="2026-01-20", amount=-300.00),
]
result = reconcile_bank_statement(
    transactions=txns, bank_account="Bank - MEL",
    candidates=candidates,
)
assert len(result.partially_matched) == 1
assert len(result.unmatched) == 1
assert result.partially_matched[0].selected.match_type == "partial"
print(f"Partial/unmatched OK | {result.summary}")
# Expected: Partial/unmatched OK | 0 matched (0.0% exact), 1 partial, 0 needs-review, 1 unmatched — 2 total
```

---

### Test 12.11 — reconcile detects multiple_matches

```python
from idp.idp.extractors.bank_statement import BankTransaction
from idp.idp.bank_reconciliation import (
    ReconciliationMatch, reconcile_bank_statement,
)

txns = [
    BankTransaction(date="2026-01-10", description="Twin",
                    debit=None, credit=100.00, balance=0.0,
                    reference=None, row_index=1),
]
candidates = [
    ReconciliationMatch(doctype="Payment Entry", name="PE-A",
                        posting_date="2026-01-10", amount=100.00),
    ReconciliationMatch(doctype="Payment Entry", name="PE-B",
                        posting_date="2026-01-10", amount=100.00),
]
result = reconcile_bank_statement(
    transactions=txns, bank_account="Bank - MEL",
    candidates=candidates,
)
assert len(result.multiple_matches) == 1
assert len(result.multiple_matches[0].candidates) == 2
print(f"Multiple-matches detection OK | candidates="
      f"{len(result.multiple_matches[0].candidates)}")
# Expected: Multiple-matches detection OK | candidates=2
```

---

### Test 12.12 — reconcile consumes each candidate only once

```python
from idp.idp.extractors.bank_statement import BankTransaction
from idp.idp.bank_reconciliation import (
    ReconciliationMatch, reconcile_bank_statement,
)

txns = [
    BankTransaction(date="2026-01-10", description="First",
                    debit=None, credit=500.00, balance=0.0,
                    reference=None, row_index=1),
    BankTransaction(date="2026-01-10", description="Second",
                    debit=None, credit=500.00, balance=0.0,
                    reference=None, row_index=2),
]
candidates = [
    ReconciliationMatch(doctype="Payment Entry", name="PE-X",
                        posting_date="2026-01-10", amount=500.00),
]
result = reconcile_bank_statement(
    transactions=txns, bank_account="Bank - MEL",
    candidates=candidates,
)
# First consumed -> matched.  Second has no remaining candidate -> unmatched.
assert len(result.matched) == 1
assert len(result.unmatched) == 1
print(f"Consume-once semantics OK | {result.summary}")
# Expected: Consume-once semantics OK | 1 matched (50.0% exact), 0 partial, 0 needs-review, 1 unmatched — 2 total
```

---

### Test 12.13 — API reconcile_bank_statement_api accepts JSON string

```python
import json
from idp.api.extract import reconcile_bank_statement_api
from idp.idp.bank_reconciliation import ReconciliationMatch

# Mock candidate pool via the underlying engine's candidates kwarg is not
# exposed via the API; instead we verify the endpoint serialises correctly
# when given an empty transactions list (nothing to reconcile).
response = reconcile_bank_statement_api(
    bank_account="Bank - Dummy",
    transactions=json.dumps([]),
)
assert response["success"] is True
assert response["reconciliation"]["counts"]["total"] == 0
print("API reconcile_bank_statement_api (empty) OK")
# Expected: API reconcile_bank_statement_api (empty) OK
```

---

### Test 12.14 — API validation errors

```python
import frappe
from idp.api.extract import (
    extract_bank_statement_api, reconcile_bank_statement_api,
)

# Missing file_url
try:
    extract_bank_statement_api(file_url="")
    raise AssertionError("Expected ValidationError")
except frappe.ValidationError:
    print("extract_bank_statement_api rejects missing file_url")

# Missing bank_account
try:
    reconcile_bank_statement_api(bank_account="", transactions="[]")
    raise AssertionError("Expected ValidationError")
except frappe.ValidationError:
    print("reconcile_bank_statement_api rejects missing bank_account")

# Invalid transactions JSON
try:
    reconcile_bank_statement_api(
        bank_account="Bank - Dummy", transactions="not-json",
    )
    raise AssertionError("Expected ValidationError")
except frappe.ValidationError:
    print("reconcile_bank_statement_api rejects invalid JSON")

# transactions must be a list
try:
    reconcile_bank_statement_api(
        bank_account="Bank - Dummy", transactions='{"x": 1}',
    )
    raise AssertionError("Expected ValidationError")
except frappe.ValidationError:
    print("reconcile_bank_statement_api rejects non-list transactions")
# Expected: all four rejection messages
```

---

### Test 12.15 — Frontend Phase-12 file structure

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp

for f in \
  frontend/src/components/BankReconciliation.vue \
  frontend/src/components/ReconciliationGroup.vue \
  frontend/src/composables/useBankReconciliation.js \
  frontend/src/pages/BankStatementView.vue; do
  if [ -f "$f" ]; then
    echo "OK: $f"
  else
    echo "MISSING: $f"
  fi
done

# Expected: all four show "OK"
```

---

### Test 12.16 — Frontend router + API wiring

```bash
cd /home/sanjay/erpnext/frappe-bench-test/apps/idp

# Route exists
grep -q "BankStatementView" frontend/src/router.js && \
  echo "Route registered" || echo "MISSING route"

# API helpers exist
grep -q "extractBankStatement" frontend/src/utils/api.js && \
  echo "extractBankStatement exported" || echo "MISSING extractBankStatement"
grep -q "reconcileBankStatement" frontend/src/utils/api.js && \
  echo "reconcileBankStatement exported" || echo "MISSING reconcileBankStatement"

# Expected:
# Route registered
# extractBankStatement exported
# reconcileBankStatement exported
```

---

## Running All Tests

### Option A: bench console (interactive)

```bash
bench --site test.local console
```

Then paste each test block above.

### Option B: bench execute (scripted)

Save a test block to a file and run:

```bash
bench --site test.local execute idp.tests.manual_test
```

### Option C: pytest (when test files are added in Phase 13)

```bash
cd apps/idp
bench --site test.local run-tests --app idp
```

---

## Test Status Tracker

| Phase | Test | Status |
|-------|------|--------|
| Phase 1 | 1.1 Constants | Completed |
| Phase 1 | 1.2 Exceptions | Completed |
| Phase 1 | 1.3 Config | Completed |
| Phase 1 | 1.4 Logger | Completed |
| Phase 2 | 2.1 Data models | Completed |
| Phase 2 | 2.2 OCR error handling | Completed |
| Phase 2 | 2.3 Image preprocessing | Completed |
| Phase 3 | 3.1 ExtractionResult | Completed |
| Phase 3 | 3.2 CSV Extractor | Completed |
| Phase 3 | 3.3 Excel Extractor | Completed |
| Phase 3 | 3.4 DOCX Extractor | Completed |
| Phase 3 | 3.5 File resolution | Completed |
| Phase 3 | 3.6 MIME detection | Completed |
| Phase 4 | 4.1 Schema discovery | Completed |
| Phase 4 | 4.2 Date normalization | Completed |
| Phase 4 | 4.3 Number normalization | Completed |
| Phase 4 | 4.4 Label-value parsing | Completed |
| Phase 4 | 4.5 Header field matching | Completed |
| Phase 4 | 4.6 Column header matching | Completed |
| Phase 4 | 4.7 Full mapping pipeline | Completed |
| Phase 5 | 5.1 Data model imports | Completed |
| Phase 5 | 5.2 Date ordering | Completed |
| Phase 5 | 5.3 Line item presence | Completed |
| Phase 5 | 5.4 Qty/rate/amount checks | Completed |
| Phase 5 | 5.5 Total checks | Completed |
| Phase 5 | 5.6 Currency validation | Completed |
| Phase 5 | 5.7 Schema required + types | Completed |
| Phase 5 | 5.8 Select options + Data length | Completed |
| Phase 5 | 5.9 Link resolution | Completed |
| Phase 5 | 5.10 Full validation pipeline | Completed |
| Phase 6 | 6.1 Imports | Completed |
| Phase 6 | 6.2 Build doc dict | Completed |
| Phase 6 | 6.3 Find missing masters | Completed |
| Phase 6 | 6.4 Auto-create masters | Completed |
| Phase 6 | 6.5 Validation error path | Completed |
| Phase 6 | 6.6 Missing master error path | Completed |
| Phase 6 | 6.7 Full end-to-end create | Completed |
| Phase 6 | 6.8 Auto-create during create | Completed |
| Phase 6 | 6.9 Text field preservation | Completed |
| Phase 7 | 7.1 Data model imports | Completed |
| Phase 7 | 7.2 Date comparison | Completed |
| Phase 7 | 7.3 Number comparison | Completed |
| Phase 7 | 7.4 String comparison | Completed |
| Phase 7 | 7.5 Non-existent record | Completed |
| Phase 7 | 7.6 Full comparison | Completed |
| Phase 7 | 7.7 Match by reference | Completed |
| Phase 7 | 7.8 Match by supplier+date+total | Completed |
| Phase 7 | 7.9 Item-level comparison | Completed |
| Phase 7 | 7.10 Summary generation | Completed |
| Phase 8 | 8.1 API module imports | Completed |
| Phase 8 | 8.2 get_settings structure | Completed |
| Phase 8 | 8.3 extract_document validation | Completed |
| Phase 8 | 8.4 extract_document error handling | Completed |
| Phase 8 | 8.5 create_erp_document validation | Completed |
| Phase 8 | 8.6 create missing master error | Completed |
| Phase 8 | 8.7 create end-to-end | Completed |
| Phase 8 | 8.8 get_missing_masters | Completed |
| Phase 8 | 8.9 compare_document validation | Completed |
| Phase 8 | 8.10 find_matching_record validation | Completed |
| Phase 8 | 8.11 JSON parameter parsing | Completed |
| Phase 8 | 8.12 Comparison serialization | Completed |
| Phase 9 | 9.1 Frontend directory structure | Completed |
| Phase 9 | 9.2 package.json structure | Completed |
| Phase 9 | 9.3 www/idp.py context provider | Completed |
| Phase 9 | 9.4 Router config matches hooks | Completed |
| Phase 9 | 9.5 API utility functions | Completed |
| Phase 9 | 9.6 Formatter utility functions | Completed |
| Phase 9 | 9.7 Vue page structure | Completed |
| Phase 9 | 9.8 Composables exports | Completed |
| Phase 11 | 11.1 DocType JSON files load | Completed |
| Phase 11 | 11.2 IDP Settings defaults | Completed |
| Phase 11 | 11.3 IDP Settings validation | Completed |
| Phase 11 | 11.4 IDP Document Log insert | Completed |
| Phase 11 | 11.5 IDP Extraction Template JSON validation | Completed |
| Phase 11 | 11.6 Workspace JSON structure | Completed |
| Phase 11 | 11.7 add_to_apps_screen hook | Completed |
| Phase 11 | 11.8 has_app_permission gating | Completed |
| Phase 11 | 11.9 IDP User role creation | Completed |
| Phase 17 | 17.1 Conversation DocType files | Completed |
| Phase 17 | 17.2 create_conversation + get_conversation | Completed |
| Phase 17 | 17.3 post_message ordering | Completed |
| Phase 17 | 17.4 IDP Message invalid role | Completed |
| Phase 17 | 17.5 Auto-title generation | Completed |
| Phase 17 | 17.6 archive_conversation | Completed |
| Phase 17 | 17.7 add_attachment dedup | Completed |
| Phase 17 | 17.8 list_conversations filter | Completed |
| Phase 17 | 17.9 Permission query conditions | Completed |
| Phase 17 | 17.10 Guest auth rejection | Completed |
| Phase 17 | 17.11 has_conversation_permission ownership | Completed |
| Phase 12 | 12.1 Module imports | Completed |
| Phase 12 | 12.2 Amount parsing | Completed |
| Phase 12 | 12.3 Date parsing | Completed |
| Phase 12 | 12.4 Header matching | Completed |
| Phase 12 | 12.5 parse_bank_statement happy path | Completed |
| Phase 12 | 12.6 Running-balance mismatch flagged | Completed |
| Phase 12 | 12.7 Missing table raises ExtractionError | Completed |
| Phase 12 | 12.8 to_dict / from_dicts round-trip | Completed |
| Phase 12 | 12.9 Exact + reference reconciliation | Completed |
| Phase 12 | 12.10 Partial and unmatched | Completed |
| Phase 12 | 12.11 Multiple-matches detection | Completed |
| Phase 12 | 12.12 Candidate consume-once | Completed |
| Phase 12 | 12.13 API reconcile accepts JSON | Completed |
| Phase 12 | 12.14 API validation errors | Completed |
| Phase 12 | 12.15 Frontend file structure | Completed |
| Phase 12 | 12.16 Frontend router + API wiring | Completed |

> **Note:** Update this table as you run tests.
> Tests for Phase 10+ should be added here as those phases are implemented.
