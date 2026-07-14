# Intelligent Document Processing (IDP) for Frappe / ERPNext
## Technical Documentation

---

## Index

1. [Overview](#1-overview)
2. [Technology Stack](#2-technology-stack)
3. [System Architecture](#3-system-architecture)
4. [Core Modules & Functions](#4-core-modules--functions)
   - 4.1 Extractors Module
   - 4.2 OCR Engine
   - 4.3 Field Mapper
   - 4.4 LLM Module (Optional AI Layer)
   - 4.5 Core Utilities
5. [Data Extraction Without AI](#5-data-extraction-without-ai)
   - 5.1 PDF Extraction (Text-Based)
   - 5.2 Image Extraction
   - 5.3 Excel/CSV Extraction
   - 5.4 Word (DOCX) Extraction
6. [Data Transformation & Enrichment Logic](#6-data-transformation--enrichment-logic)
7. [Extracted Data Mapping Logic](#7-extracted-data-mapping-logic)
8. [Document Creation in ERPNext](#8-document-creation-in-erpnext)
9. [Detailed Process Flow Diagram](#9-detailed-process-flow-diagram)
10. [Supported Document Types](#10-supported-document-types)
11. [Configuration & Settings](#11-configuration--settings)

---

## 1. Overview

The IDP (Intelligent Document Processing) application is a modern, conversational document-processing app built for Frappe/ERPNext. It enables users to upload invoices, purchase orders, delivery notes, bank statements, or quotations, after which the IDP agent extracts structured data, reconciles it against existing ERPNext records, and creates or updates documents.

The application is designed with a **dual-layer approach**:
- **Rule-based extraction** (no AI required) for structured data mapping
- **Optional LLM fallback** for low-confidence extractions or complex documents

---

## 2. Technology Stack

### Backend (Frappe App)
| Component | Technology |
|-----------|------------|
| **Framework** | Frappe Framework v16+ |
| **ERP** | ERPNext v16+ |
| **Python** | Python 3.14+ |
| **OCR Engine** | PaddleOCR with 12+ languages |
| **PDF Processing** | pypdf |
| **Excel Processing** | openpyxl |
| **Word Processing** | python-docx |
| **Image Processing** | Pillow (PIL) |
| **LLM Providers** | OpenAI, Anthropic, Ollama (optional) |

### Frontend
| Component | Technology |
|-----------|------------|
| **UI Framework** | Vue 3, Vite, Tailwind CSS, Frappe UI |
| **Real-time** | Socket.IO / WebSocket via Frappe Realtime |

### Key Python Packages
- `paddleocr` – OCR and table extraction
- `pypdf` – PDF text extraction
- `openpyxl` – Excel file parsing
- `python-docx` – Word document parsing
- `Pillow` – Image preprocessing
- `openai` / `anthropic` – LLM integration (optional)

---

## 3. System Architecture

The IDP application follows a modular, pipeline-based architecture:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE (Vue 3)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │   Chat UI    │  │  Sidebar     │  │  ConfirmationCard         │ │
│  │  (Composer)  │  │ (History)    │  │  (Editable Fields)        │ │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         API LAYER (idp/api)                        │
│              ┌──────────────────────────────────────┐              │
│              │   IDP API Client (CSRF + Streaming)  │              │
│              └──────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       CORE PROCESSING PIPELINE                      │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐ │
│  │  EXTRACTORS  │───▶│  OCR ENGINE  │───▶│    FIELD MAPPER      │ │
│  │  (PDF/Image/ │    │  (PaddleOCR) │    │  (Rule-based + LLM)  │ │
│  │   Excel/CSV/ │    │              │    │                      │ │
│  │   Word)      │    └──────────────┘    └──────────────────────┘ │
│  └──────────────┘             │                     │              │
│                               ▼                     ▼              │
│                    ┌──────────────────┐  ┌──────────────────────┐ │
│                    │  VISION FALLBACK │  │  DOCUMENT CREATOR    │ │
│                    │  (Ollama/LLaVA)  │  │  (ERPNext Write)     │ │
│                    └──────────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ERPNext DATABASE                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │Purchase  │ │  Sales   │ │  Quota-  │ │  Payment Entry /     │ │
│  │Invoice   │ │  Invoice │ │  tion    │ │  Journal Entry       │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Core Modules & Functions

### 4.1 Extractors Module (`idp/extractors/`)

The extractors module provides concrete implementations for every supported file format.

#### Base Classes

| Class | File | Purpose |
|-------|------|---------|
| `BaseExtractor` | `base.py` | Abstract base class defining the extraction interface |
| `ExtractionResult` | `base.py` | Unified data structure returned by all extractors |

#### Concrete Extractors

| Class | File | Supported MIME Types | Key Functions |
|-------|------|---------------------|---------------|
| **`PDFExtractor`** | `extractor.py` | `application/pdf` | `extract()`, `_extract_text_pypdf()`, `_get_page_count()` |
| **`ImageExtractor`** | `extractor.py` | `image/png`, `image/jpeg`, `image/webp`, `image/tiff` | `extract()` |
| **`ExcelExtractor`** | `extractor.py` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `application/vnd.ms-excel` | `extract()` |
| **`CSVExtractor`** | `extractor.py` | `text/csv` | `extract()`, `_read_file()`, `_detect_dialect()` |
| **`DocxExtractor`** | `extractor.py` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `extract()` |

#### Key Functions

```python
# PDFExtractor.extract() - Core extraction flow
def extract(self, file_path: str, **kwargs) -> ExtractionResult:
    # 1. Extract text via pypdf
    text = self._extract_text_pypdf(file_path)
    # 2. Check if vision fallback is needed (scanned PDF)
    if needs_vision_fallback(text, page_count):
        # 3. Fall back to PaddleOCR
        ocr_results = process_pdf(file_path, lang=lang)
    # 4. Extract tables via OCR
    tables = extract_tables(...)
    # 5. Return unified ExtractionResult
    return ExtractionResult(...)
```


---

### 4.2 OCR Engine (`idp/ocr/engine.py`)

The OCR engine provides a PaddleOCR wrapper with singleton pattern for document extraction.

#### Data Models

| Class | Purpose |
|-------|---------|
| `TextBlock` | A single recognised text region with confidence and bounding box |
| `Table` | A table extracted from a document page |
| `LayoutRegion` | A single layout region (title, text, table, figure) |
| `LayoutAnalysis` | Full layout analysis for a page |
| `OCRResult` | Structured OCR result for a single page |

#### Key Functions

| Function | Purpose |
|----------|---------|
| `get_ocr_engine(lang)` | Singleton OCR engine instance per language |
| `get_structure_engine(lang)` | Singleton PPStructureV3 instance for table/layout extraction |
| `preprocess_image(image_path)` | Image preprocessing: grayscale, contrast enhancement, sharpening, upscaling |
| `extract_text(file_path, lang)` | Extract text with bounding boxes |
| `extract_table(file_path, lang)` | Extract table structures via PPStructure |

#### Image Preprocessing Steps

1. Convert to grayscale
2. Enhance contrast (1.5x boost)
3. Apply light sharpening
4. Upscale small images (width < 1500px)

---

### 4.3 Field Mapper (`idp/mappers/mapper.py`)

The FieldMapper is a **rule-based mapping engine** that maps extracted document content to ERPNext DocType fields using keyword matching, regex-based value-type detection, and fuzzy link resolution — **with no LLM required**.

#### Field Keywords per DocType

The mapper maintains a comprehensive keyword dictionary for each supported DocType:

| DocType | Mapped Fields | Example Keywords |
|---------|---------------|------------------|
| **Purchase Invoice** | `supplier`, `posting_date`, `due_date`, `bill_no`, `taxes_and_charges`, `net_total`, `grand_total` | "supplier", "vendor", "seller", "invoice date", "bill no" |
| **Sales Invoice** | `customer`, `posting_date`, `due_date`, `po_no`, `taxes_and_charges`, `net_total`, `grand_total` | "customer", "buyer", "client", "po no" |
| **Purchase Order** | `supplier`, `transaction_date`, `schedule_date`, `net_total`, `grand_total` | "order date", "delivery date" |
| **Sales Order** | `customer`, `transaction_date`, `delivery_date`, `po_no`, `net_total`, `grand_total` | "so date", "ship date" |
| **Quotation** | `party_name`, `transaction_date`, `valid_till`, `net_total`, `grand_total` | "quote to", "valid till" |
| **Payment Entry** | `party`, `posting_date`, `paid_amount`, `reference_no`, `reference_date`, `mode_of_payment` | "paid to", "cheque no", "utr" |
| **Journal Entry** | `posting_date`, `cheque_no`, `cheque_date`, `total_debit`, `total_credit`, `remark` | "journal date", "narration" |

#### Item-Level Keyword Mappings

Shared across all DocTypes:

| Field | Keywords |
|-------|----------|
| `item_code` | "item code", "item no", "product code", "sku", "part no" |
| `item_name` | "item", "item name", "description", "product", "particulars" |
| `qty` | "qty", "quantity", "units", "nos", "pcs" |
| `rate` | "rate", "unit price", "price", "unit cost" |
| `amount` | "amount", "total", "line total", "value" |
| `uom` | "uom", "unit", "unit of measure" |
| `discount_percentage` | "discount", "disc", "disc %" |

#### Regex Patterns for Value Detection

| Pattern Type | Purpose |
|--------------|---------|
| `DATE_PATTERNS` | Detect dates in ISO, DD/MM/YYYY, MM/DD/YYYY, DD-Mon-YYYY, Mon DD, YYYY formats |
| `CURRENCY_PATTERN` | Detect currency symbols and codes (₹, $, €, £, ¥, INR, USD, EUR, etc.) |
| `NUMBER_PATTERN` | Detect numeric values |

#### Field Alias Normalization

Common field aliases are normalized to standard ERPNext field names:

| Alias | Normalized Field |
|-------|------------------|
| `terms_and_conditions` | `terms` |
| `bank_details` | `remarks` |
| `vat` / `gst` | `taxes` |
| `tax_amount` | `total_taxes_and_charges` |
| `subtotal` | `net_total` |
| `grand_total` / `total_amount` | `grand_total` |

---

### 4.4 LLM Module (`idp/llm/`) – Optional AI Layer

While the core extraction is rule-based, the IDP includes an optional LLM layer for:

| Purpose | Description |
|---------|-------------|
| **Classification** | Document type identification |
| **Extraction** | Low-confidence field extraction |
| **Vision** | OCR fallback via Ollama (minicpm-v, llava) |
| **Summarisation** | Document summarization |
| **Confirmation** | Final confirmation of extracted data |

---

### 4.5 Core Utilities (`idp/core/`)

| Module | Purpose |
|--------|---------|
| `audit.py` | Audit logging for document operations |
| `cache.py` | Mapper output cache keyed by `(file_hash, target_doctype, mapper_version)` |
| `config.py` | IDP Settings configuration |
| `constants.py` | System constants (MAX_PAGES_PER_PDF, etc.) |
| `errors.py` / `exceptions.py` | Custom exception classes |
| `file_io.py` | File I/O utilities |
| `logger.py` | Structured logging |
| `metrics.py` | Cost/token/duration tracking |

---

## 5. Data Extraction Without AI

### 5.1 PDF Extraction (Text-Based)

**Flow:**

1. **Text Extraction**: Uses `pypdf.PdfReader` to extract text from all pages
2. **Vision Gating**: Checks if the extracted text meets the threshold:
   - Total characters < `vision_text_threshold` (default: 200) → fallback to OCR
   - Alphanumeric ratio < 0.05 → fallback to OCR
   - Sparse text (< 50 chars/page) → fallback to OCR
3. **Table Extraction**: Uses PaddleOCR PPStructure for table detection
4. **Result**: Returns `ExtractionResult` with text, tables, and metadata

**Code Example:**

```python
def extract(self, file_path: str, **kwargs) -> ExtractionResult:
    text = self._extract_text_pypdf(file_path)
    page_count = self._get_page_count(file_path)
    
    if needs_vision_fallback(text, page_count):
        ocr_results = process_pdf(file_path, lang=lang)
        # Rebuild text from OCR results
        text = "\n\n".join(page_text for page in ocr_results)
        tables = [tbl.rows for page in ocr_results for tbl in page.tables]
    else:
        # Text-based PDF — still try table extraction via OCR
        ocr_results = process_pdf(file_path, lang=lang)
        tables = [tbl.rows for page in ocr_results for tbl in page.tables]
    
    return ExtractionResult(content_type="mixed" if tables else "text", ...)
```


---

### 5.2 Image Extraction

**Flow:**

1. **Preprocessing**: Convert to grayscale, enhance contrast, sharpen, upscale if needed
2. **Text Extraction**: Run PaddleOCR text extraction
3. **Table Extraction**: Run PaddleOCR table extraction
4. **Result**: Returns `ExtractionResult` with text, tables, and confidence scores

**Key Functions:**

```python
preprocessed = preprocess_image(file_path)
text_dicts = extract_text(preprocessed, lang=lang)
full_text = "\n".join(d["text"] for d in text_dicts)
table_objs = extract_table(preprocessed, lang=lang)
tables = [t.rows for t in table_objs]
```


---

### 5.3 Excel/CSV Extraction

**Excel Flow:**

1. Load workbook using `openpyxl.load_workbook` (read-only, data-only mode)
2. Iterate through all sheets
3. Parse rows, skip completely empty rows
4. Build tabular representation

**CSV Flow:**

1. Auto-detect encoding (utf-8, utf-8-sig, latin-1, cp1252)
2. Auto-detect delimiter (comma, semicolon, tab, pipe) using `csv.Sniffer`
3. Parse header row + data rows
4. Return as tabular `ExtractionResult`

---

### 5.4 Word (DOCX) Extraction

**Flow:**

1. Load document using `python-docx.Document`
2. Extract paragraphs (with style metadata)
3. Extract tables (rows × columns)
4. Return text + tables as `ExtractionResult`

---

## 6. Data Transformation & Enrichment Logic

### 6.1 Field Alias Normalization

Extracted field names are normalized to standard ERPNext field names using `FIELD_ALIASES` mapping.

### 6.2 Date Parsing

Multiple date formats are supported via regex patterns:

| Format | Example | Pattern |
|--------|---------|---------|
| ISO | 2026-04-02 | `\b(\d{4})-(\d{1,2})-(\d{1,2})\b` |
| DD/MM/YYYY | 02/04/2026 | `\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b` |
| DD-Mon-YYYY | 02-Apr-2026 | `\b(\d{1,2})[/\-.\s]([A-Za-z]{3,9})[/\-.\s](\d{4})\b` |
| Mon DD, YYYY | April 02, 2026 | `\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b` |

### 6.3 Currency Detection

Currency values are detected using regex patterns for symbols and codes:

```
[₹$€£¥]?\s*[\d,]+\.?\d*|[\d.,]+\s*(?:INR|USD|EUR|GBP|JPY|Rs\.?|AUD|CAD)
```

### 6.4 Link Field Resolution

For Link-type fields (Customer, Supplier, Item, etc.), fuzzy matching is performed using display fields:

| Link DocType | Display Field |
|--------------|---------------|
| Customer | `customer_name` |
| Supplier | `supplier_name` |
| Item | `item_name` |
| Employee | `employee_name` |
| Account | `account_name` |
| Warehouse | `warehouse_name` |

### 6.5 Master Auto-Creation

Missing masters (Supplier, Customer, Item) can be auto-created when enabled in settings.

### 6.6 Cache Mechanism

Mapper output is cached keyed by `(file_hash, target_doctype, mapper_version)` to skip LLM calls on re-upload.

---

## 7. Extracted Data Mapping Logic

### 7.1 Rule-Based Mapping Process

The `FieldMapper` class implements a rule-based mapping engine:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     EXTRACTION RESULT                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  text: "Invoice No. INV-2026-0042\nDate: 02/04/2026\n..."  │  │
│  │  tables: [[...], [...]]                                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FIELD KEYWORD MATCHING                         │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  For each field in DocType schema:                          │  │
│  │    - Match keywords against extracted text                  │  │
│  │    - Extract value using regex patterns                     │  │
│  │    - Normalize field aliases                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     VALUE TYPE DETECTION                           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  - Date detection (multiple formats)                        │  │
│  │  - Currency detection                                        │  │
│  │  - Number detection                                          │  │
│  │  - Link resolution (Customer, Supplier, Item, etc.)         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     LOW-CONFIDENCE FALLBACK                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  If confidence < threshold:                                 │  │
│  │    - Use LLM hybrid mapping (optional)                      │  │
│  │    - Inject few-shot exemplars from corrections             │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     MAPPED DOCUMENT                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  {                                                          │  │
│  │    "doctype": "Purchase Invoice",                           │  │
│  │    "supplier": "Tara Technologies",                         │  │
│  │    "posting_date": "2026-04-02",                            │  │
│  │    "bill_no": "INV-2026-0042",                              │  │
│  │    "items": [{"item_code": "..., "qty": ..., "rate": ...}] │  │
│  │  }                                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Pre-Validation Against Schema

Before the extraction loop runs, validation is performed against the target DocType's schema:
- Required-field validation
- Range validation
- Regex validation
- `in [...]` rules validation

---

## 8. Document Creation in ERPNext

### 8.1 Creation Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CONFIRMATION CARD (UI)                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  User reviews extracted data, edits fields if needed        │  │
│  │  User clicks "Create Document"                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DOCUMENT CREATOR                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  - Validates all required fields                            │  │
│  │  - Resolves missing masters (optional)                      │  │
│  │  - Creates document in ERPNext                              │  │
│  │  - Returns document name and link                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ERPNext DATABASE                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Document created with all mapped fields                    │  │
│  │  Audit log recorded                                          │  │
│  │  Undo window available (default 5 minutes)                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Key Functions (in `document_creator.py`)

| Function | Purpose |
|----------|---------|
| `create_document(mapped_data)` | Creates a new ERPNext document from mapped data |
| `resolve_masters(data)` | Auto-resolves missing Supplier/Customer/Item masters |
| `validate_required_fields(data)` | Validates that all required fields are present |
| `apply_undo_window(doc)` | Applies undo window (default 5 minutes) |

### 8.3 Rollout Modes

| Mode | Setting | Behavior |
|------|---------|----------|
| **Dry-run** | `Enable Write Operations` = OFF | Users see ConfirmationCards but no ERPNext records are created |
| **Live** | `Enable Write Operations` = ON | Documents are created in ERPNext |

### 8.4 Supported Target DocTypes

The following DocTypes are supported out of the box:

| DocType | Purpose |
|---------|---------|
| Purchase Invoice | Supplier billing |
| Sales Invoice | Customer billing |
| Quotation | Sales quotes |
| Sales Order | Customer orders |
| Purchase Order | Supplier orders |
| Delivery Note | Shipment documentation |
| Purchase Receipt | Goods receipt |
| Payment Entry | Payment processing |
| Journal Entry | Accounting entries |
| Bank Statement | Bank reconciliation |

Custom DocTypes can be supported by adding an `IDP Extraction Template`.

---

## 9. Detailed Process Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           USER INTERACTION FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────┐                                                               │
│  │   USER      │                                                               │
│  └──────┬──────┘                                                               │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  1. UPLOAD DOCUMENT                                                      │  │
│  │     - Drag-and-drop or file picker                                       │  │
│  │     - Supported: PDF, Image, Excel, CSV, Word                           │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  2. FILE TYPE DETECTION                                                   │  │
│  │     - MIME type detection                                                 │  │
│  │     - Select appropriate extractor                                        │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  3. DATA EXTRACTION (NO AI)                                               │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  PDF:                                                            │    │  │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │    │  │
│  │  │  │ pypdf text     │─▶│ Vision gating  │─▶│ PaddleOCR (if   │  │    │  │
│  │  │  │ extraction     │  │ (threshold     │  │ scanned/        │  │    │  │
│  │  │  │                │  │  check)        │  │ sparse)         │  │    │  │
│  │  │  └────────────────┘  └────────────────┘  └──────────────────┘  │    │  │
│  │  │                                                                  │    │  │
│  │  │  Image:                                                          │    │  │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │    │  │
│  │  │  │ Preprocess     │─▶│ PaddleOCR      │─▶│ Table extraction │  │    │  │
│  │  │  │ (grayscale,    │  │ text extraction │  │ (PPStructure)   │  │    │  │
│  │  │  │  sharpen,      │  │                │  │                  │  │    │  │
│  │  │  │  upscale)      │  │                │  │                  │  │    │  │
│  │  │  └────────────────┘  └────────────────┘  └──────────────────┘  │    │  │
│  │  │                                                                  │    │  │
│  │  │  Excel/CSV:                                                      │    │  │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │    │  │
│  │  │  │ openpyxl /     │─▶│ Parse rows     │─▶│ Build tabular    │  │    │  │
│  │  │  │ csv.Sniffer    │  │ (skip empty)   │  │ representation   │  │    │  │
│  │  │  └────────────────┘  └────────────────┘  └──────────────────┘  │    │  │
│  │  │                                                                  │    │  │
│  │  │  Word:                                                          │    │  │
│  │  │  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │    │  │
│  │  │  │ python-docx    │─▶│ Extract        │─▶│ Extract tables   │  │    │  │
│  │  │  │ Document load  │  │ paragraphs     │  │                  │  │    │  │
│  │  │  └────────────────┘  └────────────────┘  └──────────────────┘  │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  4. FIELD MAPPING (RULE-BASED)                                           │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  a. Keyword Matching                                            │    │  │
│  │  │     - Match FIELD_KEYWORDS against extracted text              │    │  │
│  │  │     - Match ITEM_KEYWORDS for line items                      │    │  │
│  │  │                                                                  │    │  │
│  │  │  b. Value Extraction                                            │    │  │
│  │  │     - Regex-based value detection (dates, currency, numbers)   │    │  │
│  │  │     - Field alias normalization                                │    │  │
│  │  │                                                                  │    │  │
│  │  │  c. Link Resolution                                             │    │  │
│  │  │     - Fuzzy match against existing records                     │    │  │
│  │  │     - Use LINK_DISPLAY_FIELDS for matching                    │    │  │
│  │  │                                                                  │    │  │
│  │  │  d. Confidence Scoring                                          │    │  │
│  │  │     - Each mapped field gets a confidence score                │    │  │
│  │  │     - Low-confidence fields flagged for review                 │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  5. LOW-CONFIDENCE FALLBACK (OPTIONAL LLM)                              │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  If confidence < threshold:                                    │    │  │
│  │  │  - Use LLM hybrid mapping                                      │    │  │
│  │  │  - Inject few-shot exemplars from corrections                  │    │  │
│  │  │  - Check cache: (file_hash, doctype, version)                  │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  6. PRE-VALIDATION                                                       │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  - Required-field validation                                    │    │  │
│  │  │  - Range validation                                            │    │  │
│  │  │  - Regex validation                                            │    │  │
│  │  │  - in [...] rules validation                                   │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  7. CONFIRMATION CARD DISPLAY                                            │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  - Editable header fields                                        │    │  │
│  │  │  - Line items with edit capabilities                            │    │  │
│  │  │  - Tax information                                              │    │  │
│  │  │  - Comparison results (if comparing against existing docs)     │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  8. USER REVIEW & CONFIRMATION                                          │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  User:                                                          │    │  │
│  │  │  - Reviews extracted data                                       │    │  │
│  │  │  - Edits fields if needed                                       │    │  │
│  │  │  - Confirms or rejects                                          │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  9. DOCUMENT CREATION                                                    │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  a. Resolve missing masters (if enabled)                       │    │  │
│  │  │  b. Create document in ERPNext                                 │    │  │
│  │  │  c. Apply undo window (default 5 min)                          │    │  │
│  │  │  d. Record audit log                                           │    │  │
│  │  │  e. Return document name and link                              │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                       │
│         ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  10. RESULT DISPLAY                                                      │  │
│  │                                                                           │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │  │
│  │  │  - Document link displayed                                       │    │  │
│  │  │  - Cost / tokens / duration footer                              │    │  │
│  │  │  - Undo option available                                        │    │  │
│  │  └─────────────────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Supported Document Types

### Out-of-the-Box Support

| DocType | Purpose | Key Mapped Fields |
|---------|---------|-------------------|
| **Purchase Invoice** | Supplier billing | supplier, posting_date, due_date, bill_no, taxes, net_total, grand_total |
| **Sales Invoice** | Customer billing | customer, posting_date, due_date, po_no, taxes, net_total, grand_total |
| **Purchase Order** | Supplier orders | supplier, transaction_date, schedule_date, net_total, grand_total |
| **Sales Order** | Customer orders | customer, transaction_date, delivery_date, po_no, net_total, grand_total |
| **Quotation** | Sales quotes | party_name, transaction_date, valid_till, net_total, grand_total |
| **Payment Entry** | Payments | party, posting_date, paid_amount, reference_no, mode_of_payment |
| **Journal Entry** | Accounting | posting_date, cheque_no, total_debit, total_credit, remark |
| **Opportunity** | Sales pipeline | party_name, transaction_date, expected_closing, opportunity_amount |
| **Supplier Quotation** | Supplier quotes | supplier, transaction_date, valid_till, quotation_number |
| **Delivery Note** | Shipments | (mapped via template) |
| **Purchase Receipt** | Goods receipt | (mapped via template) |
| **Bank Statement** | Reconciliation | (bank reconciliation engine) |

### Custom DocTypes

Custom DocTypes can be supported by adding an `IDP Extraction Template` with:
- Override keywords
- Validation rules
- Confidence bands
- LLM fallback thresholds

---

## 11. Configuration & Settings

### 11.1 IDP Settings (`/app/idp-settings`)

| Setting | Description |
|---------|-------------|
| **Enabled** | Master toggle for IDP functionality |
| **LLM Provider** | OpenAI / Anthropic / Ollama |
| **LLM Model Routes** | Per-purpose models (classification, extraction, vision, summarisation, confirmation) |
| **Default OCR Language** | en, hi, auto, etc. |
| **Default Output Language** | English, हिन्दी, etc. |
| **Confidence Threshold** | Minimum confidence for auto-accept |
| **Max File Size** | Upload limit |
| **Max Pages per PDF** | Page processing limit |
| **Enable Write Operations** | Dry-run vs. Live mode |
| **Auto-Create Masters** | Auto-create missing Supplier/Customer/Item |
| **Page Pre-Pass** | Cost-aware page processing |
| **Mapper Output Cache** | Cache extracted data |
| **Undo Window** | Default 5 minutes |
| **Active Retention** | Days to keep active conversations |

### 11.2 Vision Gating Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `vision_text_threshold` | 200 chars | Minimum text characters before vision fallback |
| `min_alpha_ratio` | 0.05 | Minimum alphanumeric ratio |

---

## Appendix: Key File References

| File | Purpose |
|------|---------|
| `idp/extractors/extractor.py` | Concrete extractor implementations |
| `idp/extractors/base.py` | Base extractor classes |
| `idp/ocr/engine.py` | PaddleOCR wrapper and singleton engine |
| `idp/mappers/mapper.py` | Rule-based field mapping engine |
| `idp/mappers/document_creator.py` | ERPNext document creation logic |
| `idp/mappers/hybrid_mapper.py` | LLM hybrid mapping for low-confidence fields |
| `idp/llm/agent.py` | LLM agent for classification, extraction, confirmation |
| `idp/core/cache.py` | Mapper output caching |
| `idp/core/audit.py` | Audit logging |

---

*For the latest information, refer to the [official repository](https://github.com/sanjay-kumar001/idp).*