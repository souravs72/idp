# IDP Extraction Template — User Manual

> **DocType:** `IDP Extraction Template`
> **Module:** IDP
> **Roles:** System Manager, IDP User
> **Auto‑name:** `field:template_name` (the template name *is* the doc name)
> **Menu path:** `/app/idp-extraction-template`

`IDP Extraction Template` lets you override the default extraction
behaviour for **a specific Target DocType** — typically a recurring
supplier‑invoice format, an industry‑specific layout, or a customer
purchase‑order template. A template can:

- Remap unusual keywords to the correct ERPNext fieldname.
- Add or override validation rules (required fields, ranges).
- Tune the **LLM fallback threshold** (when the hybrid mapper should
  call the LLM).
- Define extra **page pre‑pass** regex patterns so important pages
  aren't replaced with placeholders.
- Customise per‑DocType confidence bands for the green / amber / red
  dots in ConfirmationCard line items.

Templates are **non‑breaking**: when none match, the global defaults
from *IDP Settings* and the built‑in FieldMapper continue to apply.

---

## 1. When to use this DocType

Create a template when:

- You repeatedly process documents with non‑standard labels (e.g. a
  vendor whose invoices say *"Tax No."* instead of *"GSTIN"*).
- A specific DocType needs a stricter (or looser) LLM‑fallback
  threshold than the global default.
- The page pre‑pass keeps dropping pages that contain a supplier‑
  specific signal (e.g. *"PAN AAACT…"*, *"DUNS …"*).
- Confidence bands for a high‑risk DocType (e.g. Journal Entry) need
  to be tightened — fewer green dots, more red dots.

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Template Name** | Data, unique | ✔ | Becomes the document name. Use a short slug, e.g. `ACME Purchase Invoice`. |
| **Target DocType** | Link → DocType | ✔ | The ERPNext DocType this template extracts into. |
| **Description** | Text | — | Free‑form notes about the template. |
| **Field Mappings** | JSON | — | Custom keyword → fieldname overrides. |
| **Validation Rules** | JSON | — | Required‑field / range / regex overrides. |
| **LLM Fallback Threshold** | Float (0.0 – 1.0) | — | Below this confidence, the hybrid mapper calls the LLM. Blank = inherit *IDP Settings*. |
| **Page Pre‑Pass Patterns (JSON)** | Long Text | — | Extra regex patterns added to the per‑DocType signal set. |
| **Confidence Amber Threshold** | Float (0.0 – 1.0), default `0.75` | — | At or above ⇒ green dot; below ⇒ amber. Blank = inherit `0.75`. |
| **Confidence Red Threshold** | Float (0.0 – 1.0), default `0.55` | — | Below ⇒ red dot regardless of mapper source. Blank = inherit `0.55`. |

The controller throws on save when **LLM Fallback Threshold** is
outside `[0.0, 1.0]`, or when **Field Mappings** / **Validation Rules**
contain malformed JSON.

---

## 3. JSON field formats

### 3.1 Field Mappings

Object whose keys are *keywords as they appear on the document* and
whose values are *fieldnames on the Target DocType*. Keys are
case‑insensitive substrings.

```json
{
  "Tax No.":        "tax_id",
  "Vendor Code":    "supplier",
  "Bill Ref":       "bill_no",
  "Cost Centre":    "cost_center",
  "PO Reference":   "po_no",
  "Due By":         "due_date"
}
```

The hybrid mapper first applies these overrides, then falls back to
the built‑in `FieldMapper` keyword set.

### 3.2 Validation Rules

Object keyed by *fieldname on the Target DocType*. Each value is a
rule descriptor:

```json
{
  "bill_no":     {"required": true},
  "grand_total": {"required": true, "min": 0, "max": 50000000},
  "tax_id":      {"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][A-Z][0-9A-Z]$"},
  "posting_date":{"required": true},
  "currency":    {"in": ["INR", "USD", "EUR"]}
}
```

Supported keys: `required` (bool), `min` / `max` (numeric), `regex`
(Python regex), `in` (list of allowed values), `max_length` (int).

### 3.3 Page Pre‑Pass Patterns

JSON **array of strings** — each entry is a Python regex appended to
the built‑in signal set for this DocType. Pages containing **any**
signal survive the pre‑pass; pages with no signal are replaced with
a placeholder before being sent to the LLM.

```json
[
  "\\bGSTIN\\b",
  "IFSC[ :]",
  "DUNS\\s*\\d{9}",
  "PO\\s*Ref(erence)?\\s*[:#]"
]
```

> Remember to escape `\` as `\\` inside JSON strings.

---

## 4. Worked example — supplier‑specific template

**Scenario.** ACME Industries sends invoices with unusual labels:
`"Bill Ref"` instead of *Invoice No.*, `"Tax No."` instead of *GSTIN*,
and `"Due By"` instead of *Due Date*. The first pre‑pass regularly
drops the only page that carries `"Bill Ref"`, so the LLM never sees
it.

**Template**

| Field | Value |
| --- | --- |
| Template Name | `ACME Purchase Invoice` |
| Target DocType | `Purchase Invoice` |
| Description | `ACME Industries — bills with non‑standard labels.` |
| LLM Fallback Threshold | `0.85` |

**Field Mappings**

```json
{
  "Bill Ref": "bill_no",
  "Tax No.":  "tax_id",
  "Due By":   "due_date"
}
```

**Validation Rules**

```json
{
  "bill_no":     {"required": true, "regex": "^ACME-\\d{6}$"},
  "grand_total": {"required": true, "min": 0},
  "tax_id":      {"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][A-Z][0-9A-Z]$"}
}
```

**Page Pre‑Pass Patterns**

```json
["Bill Ref[ :]", "Tax No\\."]
```

**Confidence Bands**

- Confidence Amber Threshold: `0.80`
- Confidence Red Threshold:   `0.60`

After save, every extraction whose target is `Purchase Invoice` and
whose supplier resolves to ACME Industries uses this template
end‑to‑end. The first call invalidates the per‑DocType template cache;
subsequent calls hit the cache directly.

---

## 5. Worked example — DocType‑wide override (no supplier)

**Scenario.** All `Journal Entry` extractions need stricter validation
and stricter confidence bands across the board.

| Field | Value |
| --- | --- |
| Template Name | `Strict Journal Entry` |
| Target DocType | `Journal Entry` |
| LLM Fallback Threshold | `0.95` |
| Confidence Amber Threshold | `0.85` |
| Confidence Red Threshold | `0.70` |

**Validation Rules**

```json
{
  "posting_date": {"required": true},
  "company":      {"required": true},
  "voucher_type": {"in": ["Journal Entry", "Bank Entry", "Cash Entry"]}
}
```

Because there is no supplier scope, the template is selected purely
by Target DocType.

---

## 6. Template selection (resolution order)

When an extraction starts, the hybrid mapper picks a template by:

1. **Exact name match** — when the caller passed `template_name`
   explicitly (e.g. via the chatbot's "Use template …" pill).
2. **Best Target DocType match** — among enabled templates whose
   `target_doctype` equals the extraction's DocType.
3. **Inherit defaults** — when nothing matches, the global IDP Settings
   apply and the built‑in FieldMapper runs unchanged.

The selected template's name is stored on the resulting
ConfirmationCard so the reviewer can see which template ran.

---

## 7. Lifecycle

1. **Create.** Use the standard *New* button. `Template Name` becomes
   the document name and must be unique.
2. **Validate.** On save, the controller checks that
   `Field Mappings` and `Validation Rules` are valid JSON and that the
   LLM fallback threshold is within `[0, 1]`.
3. **Use.** Templates take effect on the very next extraction — no
   restart needed.
4. **Edit.** Updating any field invalidates the template cache.
5. **Disable.** There is no `enabled` flag. To stop using a template,
   delete it or remove its `Target DocType` so the selector can never
   find it.

---

## 8. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |
| IDP User | ✔ | ✔ | ✔ | ✖ |

IDP Users can author templates but only System Managers may delete
them.

---

## 9. Tips & best practices

- **Name templates clearly.** Prefer
  `<Supplier> <DocType>` (e.g. *ACME Purchase Invoice*) or
  `Strict <DocType>` when DocType‑wide.
- **Validate one rule at a time.** When you add a new
  `validation_rules` entry, run a few extractions and watch the audit
  log before adding more.
- **Pre‑pass patterns are powerful.** Adding `"Bill Ref"` to the
  pattern set is often cheaper than turning the pre‑pass off entirely.
- **Reuse, don't fork.** When two suppliers share a label pattern,
  consider a single template with both mappings instead of two
  near‑identical templates.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| *Field Mappings is not valid JSON* on save | Trailing comma or unescaped `\` | Run the JSON through a linter; remember `\\` inside strings. |
| *LLM Fallback Threshold must be between 0.0 and 1.0* | Entered as `85` instead of `0.85` | Use a fraction. |
| Template is set but values still go to defaults | Cache not invalidated, or `Target DocType` mismatch | Resave the template; double‑check the DocType slug. |
| Page pre‑pass keeps dropping a needed page | Signal pattern missing | Add a regex for the page's distinguishing label to **Page Pre‑Pass Patterns**. |
| Too many red dots after enabling template | Bands too strict | Raise **Confidence Red Threshold**. |

---

## 11. Related DocTypes

- **IDP Extraction Correction** — feedback exemplars; useful when a
  template still misses a field.
- **IDP Settings → Hybrid Mapper** — global thresholds inherited by
  this template.
- **IDP Prompt Template / IDP Skill** — affect the LLM prompt
  *contents*; the extraction template affects the mapping and
  validation around it.
