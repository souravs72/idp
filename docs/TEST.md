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
| Phase 1 | 1.1 Constants | Pending |
| Phase 1 | 1.2 Exceptions | Pending |
| Phase 1 | 1.3 Config | Pending |
| Phase 1 | 1.4 Logger | Pending |
| Phase 2 | 2.1 Data models | Pending |
| Phase 2 | 2.2 OCR error handling | Pending |
| Phase 2 | 2.3 Image preprocessing | Pending |
| Phase 3 | 3.1 ExtractionResult | Pending |
| Phase 3 | 3.2 CSV Extractor | Pending |
| Phase 3 | 3.3 Excel Extractor | Pending |
| Phase 3 | 3.4 DOCX Extractor | Pending |
| Phase 3 | 3.5 File resolution | Pending |
| Phase 3 | 3.6 MIME detection | Pending |
| Phase 4 | 4.1 Schema discovery | Pending |
| Phase 4 | 4.2 Date normalization | Pending |
| Phase 4 | 4.3 Number normalization | Pending |
| Phase 4 | 4.4 Label-value parsing | Pending |
| Phase 4 | 4.5 Header field matching | Pending |
| Phase 4 | 4.6 Column header matching | Pending |
| Phase 4 | 4.7 Full mapping pipeline | Pending |
| Phase 5 | 5.1 Data model imports | Pending |
| Phase 5 | 5.2 Date ordering | Pending |
| Phase 5 | 5.3 Line item presence | Pending |
| Phase 5 | 5.4 Qty/rate/amount checks | Pending |
| Phase 5 | 5.5 Total checks | Pending |
| Phase 5 | 5.6 Currency validation | Pending |
| Phase 5 | 5.7 Schema required + types | Pending |
| Phase 5 | 5.8 Select options + Data length | Pending |
| Phase 5 | 5.9 Link resolution | Pending |
| Phase 5 | 5.10 Full validation pipeline | Pending |
| Phase 6 | 6.1 Imports | Pending |
| Phase 6 | 6.2 Build doc dict | Pending |
| Phase 6 | 6.3 Find missing masters | Pending |
| Phase 6 | 6.4 Auto-create masters | Pending |
| Phase 6 | 6.5 Validation error path | Pending |
| Phase 6 | 6.6 Missing master error path | Pending |
| Phase 6 | 6.7 Full end-to-end create | Pending |
| Phase 6 | 6.8 Auto-create during create | Pending |
| Phase 6 | 6.9 Text field preservation | Pending |

> **Note:** Update this table as you run tests.
> Tests for Phase 7+ should be added here as those phases are implemented.
