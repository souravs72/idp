# IDP Extraction Correction — User Manual

> **DocType:** `IDP Extraction Correction`
> **Module:** IDP
> **Roles:** System Manager, IDP User
> **Auto‑name:** `CORR-{YYYY}-{######}` (e.g. `CORR-2026-000123`)
> **Menu path:** `/app/idp-extraction-correction`

`IDP Extraction Correction` is the **learning ledger** of the IDP module.
Every time a user edits a field value that the extractor proposed, a
correction record is written. Those corrections feed two downstream
loops:

1. **Few‑shot prompting** — recent corrections are appended to the LLM
   system prompt as `"input → output"` exemplars on subsequent
   extractions for the same DocType / supplier.
2. **Rule‑mapper tuning** — fields that the rule mapper consistently
   gets wrong surface in admin dashboards so their keywords can be
   added to the built‑in mapping table.

Corrections are rarely created by hand — they are produced
automatically by the chatbot review screen and the API helper
`idp.advanced.feedback.record_correction`. Open this DocType when you
need to **review, filter, or curate** the feedback that the model will
learn from.

---

## 1. When to use this DocType

- Inspect what the model got wrong on a specific supplier or DocType.
- Verify that the corrections feed contains clean, non‑duplicate data
  before turning **few‑shot prompting** on.
- Manually flag a correction as **Used in Few‑Shot Prompt**.
- Add a one‑off manual correction (origin `manual`) to teach the model
  about a stubborn label.

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **User** | Link → User | ✔ | Person who made the correction. |
| **Target DocType** | Link → DocType | ✔ | The ERPNext DocType being extracted (e.g. `Purchase Invoice`). |
| **Fieldname** | Data | ✔ | The fieldname on *Target DocType* that was wrong (e.g. `posting_date`). |
| **Extracted Value** | Long Text | — | What the model proposed. May be blank when the model missed the field. |
| **Corrected Value** | Long Text | ✔ | The value the user chose instead. Cannot equal *Extracted Value*. |
| **Source File URL** | Data | — | The file URL the value came from (`/files/...` or `/private/files/...`). |
| **Source Text Snippet** | Long Text | — | Up to 4000 chars of OCR text around the field — used as the *input* side of the few‑shot exemplar. |
| **Supplier / Customer** | Data | — | Counterparty hint used when grouping corrections per supplier. |
| **Template Used** | Link → IDP Extraction Template | — | The template active when the value was extracted. |
| **Origin** | Select (`rule`, `llm`, `template`, `manual`) | ✔ | Where the *wrong* value came from. Defaults to `rule`. |
| **Used in Few‑Shot Prompt** | Check | — | Set to `1` by the prompt builder once this correction has been promoted into the active prompt. Manually toggle to include/exclude. |

---

## 3. How corrections are created

### 3.1 From the chatbot review screen (the normal path)

1. The user uploads a document.
2. The extractor proposes values; the user opens the **ConfirmationCard**.
3. The user edits any field's value and clicks *Save / Confirm*.
4. For each changed field, the frontend calls
   `idp.advanced.feedback.record_correction` with the `user`,
   `target_doctype`, `fieldname`, original `extracted_value`,
   `corrected_value`, the file URL, and the surrounding text snippet.
5. A new `IDP Extraction Correction` row is created. The autoname is
   `CORR-YYYY-NNNNNN`.

### 3.2 Programmatically

```python
from idp.advanced.feedback import record_correction

correction_name = record_correction(
    user="user@example.com",
    target_doctype="Purchase Invoice",
    fieldname="posting_date",
    extracted_value="2025-12-13",
    corrected_value="2026-01-13",
    source_file_url="/private/files/acme-invoice-0421.pdf",
    source_text_snippet="Invoice Date: 13 Jan 2026  ...",
    supplier_or_customer="ACME Industries",
    template_used="ACME Purchase Invoice",
    origin="llm",
)
```

The helper rejects no‑op corrections silently:

- empty `corrected_value` → `ValueError`
- `extracted_value.strip() == corrected_value.strip()` → `ValueError`

### 3.3 By hand (rare — direct entry)

1. Go to `/app/idp-extraction-correction/new`.
2. Fill **User**, **Target DocType**, **Fieldname**, **Corrected Value**.
3. Set **Origin** = `manual`.
4. Save.

Manual rows are accepted by the few‑shot builder the same way as
auto‑recorded ones.

---

## 4. Sample records

### 4.1 Auto‑recorded — LLM misread an invoice date

```text
Name:                CORR-2026-000412
User:                ar.clerk@example.com
Target DocType:      Purchase Invoice
Fieldname:           bill_date
Extracted Value:     2025-12-13
Corrected Value:     2026-01-13
Source File URL:     /private/files/acme-2026-01-13.pdf
Source Text Snippet: "Invoice Date: 13 Jan 2026 ... Due: 12 Feb 2026"
Supplier/Customer:   ACME Industries
Template Used:       ACME Purchase Invoice
Origin:              llm
Used in Few-Shot:    0
```

### 4.2 Auto‑recorded — rule mapper picked the wrong column

```text
Name:                CORR-2026-000413
User:                inventory.lead@example.com
Target DocType:      Purchase Invoice Item
Fieldname:           qty
Extracted Value:     12
Corrected Value:     120
Source File URL:     /private/files/acme-2026-01-13.pdf
Source Text Snippet: "STEEL ROD 10MM   120 PCS   ₹85   ₹10,200"
Supplier/Customer:   ACME Industries
Origin:              rule
Used in Few-Shot:    1
```

### 4.3 Manual — teach the model an exotic label

```text
Target DocType:      Purchase Invoice
Fieldname:           supplier
Extracted Value:     (blank)
Corrected Value:     ACME Industries
Source Text Snippet: "Vendor / 売り手: ACME Industries Pvt. Ltd."
Origin:              manual
```

---

## 5. Daily workflow

### 5.1 Reviewer (IDP User)

1. Open the list view filtered by **Target DocType** = the document
   type they own (e.g. *Purchase Invoice*).
2. Sort by **Modified** descending.
3. Spot any *Corrected Value* that looks wrong — fix it in place. The
   value will be re‑used by the few‑shot builder.
4. Tick **Used in Few‑Shot Prompt** on the strongest exemplars (clean,
   self‑contained, representative).

### 5.2 Administrator (System Manager)

1. Use the standard report view to group by **Supplier / Customer** —
   suppliers with many corrections are good candidates for a dedicated
   `IDP Extraction Template`.
2. Group by **Fieldname** to find fields the rule mapper misses — those
   keywords should be added to the FieldMapper keyword set.
3. Periodically clear stale entries (`Used in Few‑Shot Prompt = 1` and
   older than your retention window).

---

## 6. Few‑shot pipeline (what happens next)

When **Enable Hybrid Mapper** is on (see *IDP Settings → Hybrid
Mapper*), the LLM prompt builder asks the feedback module for recent
exemplars:

```python
from idp.advanced.feedback import build_few_shot_examples

examples = build_few_shot_examples(
    target_doctype="Purchase Invoice",
    supplier_or_customer="ACME Industries",
    limit=5,
)
# → [FewShotExample(fieldname="bill_date", source_snippet="...", value="2026-01-13"), ...]
```

The exemplars are appended to the system prompt under a section like:

```
### Past Corrections (use as guidance, do not echo verbatim)
- bill_date:
    snippet: "Invoice Date: 13 Jan 2026 ..."
    expected: 2026-01-13
- qty:
    snippet: "STEEL ROD 10MM   120 PCS   ₹85   ₹10,200"
    expected: 120
```

Once an exemplar is consumed, the builder sets
**Used in Few‑Shot Prompt** = `1`.

---

## 7. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |
| IDP User | ✔ | ✔ | ✔ | ✖ |

IDP Users can create and edit corrections (so the review screen works),
but only System Managers can delete them.

---

## 8. Tips & best practices

- **Quality over quantity.** A handful of clean exemplars per DocType
  beats hundreds of duplicates. Tick *Used in Few‑Shot* deliberately.
- **Snippet matters.** Include the *label* next to the value in the
  source snippet — the LLM learns the *labelling pattern*, not just the
  value.
- **Origin = `manual`** is fine but unaudited. Track when and why you
  added each manual row.
- **Per‑supplier templates first.** If one supplier accumulates many
  corrections, build an `IDP Extraction Template` instead of relying on
  few‑shot.
- **Privacy.** `Source Text Snippet` may contain PII — apply normal
  retention to this DocType.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Few‑shot prompts contain stale guidance | `Used in Few‑Shot Prompt` = `1` rows not pruned | Filter on that flag and delete or update the rows. |
| `record_correction` raises *ValueError: identical* | Frontend submitted unchanged value | Verify the diff logic; skip writes when the value did not change. |
| Same fieldname keeps appearing for one supplier | Rule mapper or template is wrong | Either patch the FieldMapper keywords or create a per‑supplier `IDP Extraction Template`. |
| No few‑shot exemplars used by the LLM | `Enable Hybrid Mapper` = off | Turn it on in *IDP Settings → Hybrid Mapper*. |

---

## 10. Related DocTypes

- **IDP Extraction Template** — fixes recurring patterns at the
  mapping level rather than the exemplar level.
- **IDP Settings → Hybrid Mapper** — master switch for the few‑shot
  loop.
- **IDP Prompt Library** — long‑form prompts; corrections augment them.
