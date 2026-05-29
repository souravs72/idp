# IDP Prompt Library — User Manual

> **DocType:** `IDP Prompt Library`
> **Module:** IDP
> **Roles:** System Manager (full), IDP User (read‑only)
> **Auto‑name:** `field:prompt_name`
> **Menu path:** `/app/idp-prompt-library`

`IDP Prompt Library` is a **catalogue of LLM system‑prompt snippets**
tuned per *industry* and (optionally) per *DocType*. Where
`IDP Prompt Template` is the active, Jinja‑rendered prompt for the live
LLM call, the Prompt Library is the *gallery* — a curated set of
reusable building blocks that admins can copy, fork, or activate.

It is also the place where the built‑in shipped prompts live (loaded
on `after_install` and `after_migrate`). You can edit, disable, or add
new entries without re‑deploying code.

---

## 1. When to use this DocType

- Audit the built‑in prompts that ship with IDP.
- Override one of those built‑ins with your own wording for an industry
  (e.g. nuanced Manufacturing prompt for *Purchase Invoice*).
- Add prompts for new industries that ship empty (Healthcare,
  Construction, …).
- Disable a prompt globally without deleting it.
- Look up the best‑matching prompt for a given *(industry, DocType)*
  pair via the helper API.

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Prompt Name** | Data, unique | ✔ | Becomes the document name. Convention: `<Industry> — <DocType / Use case>`. |
| **Industry** | Select | ✔ | One of: `Generic`, `Manufacturing`, `Retail`, `Services`, `Logistics`, `Healthcare`, `Construction`, `Finance`. Defaults to `Generic`. |
| **Target DocType** | Link → DocType | — | Optional ERPNext DocType. Empty = applies to any DocType in that industry. |
| **Description** | Small Text | — | One‑line summary shown in the list view. |
| **Enabled** | Check (default `1`) | — | Disable to keep the row but exclude it from lookups. |
| **Prompt Body** | Long Text | ✔ | The actual system‑prompt text. Plain Markdown — Jinja is **not** evaluated here (use *IDP Prompt Template* for Jinja). |
| **Example Input** | Long Text | — | Optional excerpt of OCR text that this prompt is designed for. |
| **Example Output** | Long Text | — | Optional reference JSON / extraction result. |

---

## 3. Built‑in catalogue (shipped on install)

The following entries are seeded automatically. You can override their
bodies; the seeder respects user edits unless run with `overwrite=True`.

| Prompt Name | Industry | Target DocType |
| --- | --- | --- |
| `Generic — Invoice Extraction` | Generic | (any) |
| `Manufacturing — Purchase Invoice` | Manufacturing | Purchase Invoice |
| `Retail — Sales Invoice` | Retail | Sales Invoice |
| `Services — Sales Invoice` | Services | Sales Invoice |
| `Logistics — Delivery Note` | Logistics | Delivery Note |
| `Finance — Payment Entry` | Finance | Payment Entry |

To re‑seed (or upgrade) the built‑ins:

```python
from idp.advanced.prompt_library import seed_builtin_prompts

# Insert any missing built‑ins; do not touch existing rows
seed_builtin_prompts()

# Force the built‑in bodies even if the user has edited them
seed_builtin_prompts(overwrite=True)
```

---

## 4. Sample record — *Manufacturing — Purchase Invoice*

```text
Prompt Name:     Manufacturing — Purchase Invoice
Industry:        Manufacturing
Target DocType:  Purchase Invoice
Description:     Supplier bills with BOM, HSN/SAC codes, batch numbers.
Enabled:         1
```

**Prompt Body**

```text
You are processing a manufacturing supplier invoice. Typical fields
include: HSN/SAC codes, batch/lot numbers, UOM (Kg/Ton/Nos/Mtr), GST
breakdowns (CGST/SGST/IGST), and multi-line items with tooling or
material specs.

Rules:
- Map every line item individually; do not merge.
- For dates, return ISO YYYY-MM-DD.
- For amounts, return bare numbers without currency symbols.
- If you see a BOM reference, place it in the remarks field.
- Never fabricate values; if a field is absent, return null.
```

**Example Input** (excerpt)

```
INV-2026-00031   Date: 13/01/2026   GSTIN: 27AAACT2727Q1ZZ
Item            HSN     Qty   UOM   Rate    Amount
Steel Rod 10mm  7308    120   PCS   85.00   10,200
Welding Flux    3810    2     KG    540.00  1,080
CGST 9%                                     1,015
SGST 9%                                     1,015
Total                                       13,310
```

**Example Output**

```json
{
  "bill_no": "INV-2026-00031",
  "bill_date": "2026-01-13",
  "tax_id": "27AAACT2727Q1ZZ",
  "items": [
    {"item_name": "Steel Rod 10mm", "hsn": "7308", "qty": 120, "uom": "PCS", "rate": 85.00, "amount": 10200},
    {"item_name": "Welding Flux",   "hsn": "3810", "qty": 2,   "uom": "KG",  "rate": 540.00, "amount": 1080}
  ],
  "taxes": [
    {"type": "CGST", "rate": 9, "amount": 1015},
    {"type": "SGST", "rate": 9, "amount": 1015}
  ],
  "grand_total": 13310
}
```

---

## 5. Sample record — *Generic — Invoice Extraction*

```text
Prompt Name:     Generic — Invoice Extraction
Industry:        Generic
Target DocType:  (blank)
Enabled:         1
Description:     Neutral prompt for any tax-invoice-like document.

Prompt Body:
You are a meticulous data-extraction assistant. The user has uploaded
a business document (invoice, PO, quotation). Extract structured
fields that match the target ERPNext DocType schema. Prefer values
found verbatim in the document; never fabricate values. For dates,
return ISO YYYY-MM-DD. For amounts, return bare numbers without
currency symbols.
```

This row acts as the **safety‑net default** — it is selected whenever
no industry‑specific or DocType‑specific prompt matches.

---

## 6. Lookup order (how the library picks a row)

```python
from idp.advanced.prompt_library import load_prompt

snippet = load_prompt(industry="Manufacturing", target_doctype="Purchase Invoice")
print(snippet.body)  # → the Manufacturing — Purchase Invoice prompt
```

`load_prompt` walks the catalogue in this exact order, returning the
first enabled match:

1. **Industry + exact DocType** match
2. **Industry only** (DocType empty)
3. **Generic + exact DocType**
4. **Generic only** (DocType empty)

This makes the system **degrade gracefully**:

- Specialise where you can — add a `Healthcare — Sales Invoice` entry.
- Fall back to `Generic` automatically when no specialisation exists.

To list everything in the catalogue:

```python
from idp.advanced.prompt_library import list_prompts

# All enabled prompts
list_prompts()

# Just Logistics, enabled or not
list_prompts(industry="Logistics", enabled_only=False)
```

---

## 7. Authoring guidelines

A good prompt body:

- Starts with a one‑sentence role statement (*"You are processing a
  manufacturing supplier invoice."*).
- Lists 4 – 8 hard rules — short, imperative.
- States the **output format** explicitly (ISO dates, bare numbers,
  null for missing).
- Avoids vendor‑specific labels (those belong in an *IDP Extraction
  Template*).
- Stays under ~ 1500 tokens. Use *IDP Skill* records for reusable rule
  blocks instead of bloating the prompt body.

---

## 8. Lifecycle

1. **Create.** Pick an `Industry`, optionally pin a `Target DocType`,
   write the `Prompt Body`. Keep `Enabled` = `1`.
2. **Disable temporarily.** Untick `Enabled` instead of deleting — the
   row stays for reference but is invisible to `load_prompt`.
3. **Edit.** Save propagates immediately; there is no cache for this
   DocType.
4. **Re‑seed built‑ins.** Run `seed_builtin_prompts(overwrite=True)`
   when the IDP module ships an upgraded default that you want to
   adopt.
5. **Delete.** Only System Managers may delete. Custom rows are safe
   to delete; built‑ins will be recreated by the next migration unless
   you also disable seeding.

---

## 9. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |
| IDP User | ✔ | ✖ | ✖ | ✖ |

The library is curated by admins; IDP Users only consume it via the
chatbot.

---

## 10. Tips & best practices

- **Use Generic as the floor.** Keep one `Generic` row per common
  DocType so unfamiliar industries still get sensible defaults.
- **Stack with skills.** Common rules ("HSN codes are 4 – 8 digits",
  "GSTIN is 15 alphanumerics") belong in an `IDP Skill`. The Prompt
  Library should hold the *industry voice*, not exhaustive rules.
- **Test with the Example Input/Output fields.** They are *not* used at
  runtime but make code review and onboarding much easier.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `load_prompt` returns `None` | No matching enabled row, not even Generic | Reseed via `seed_builtin_prompts()`. |
| Wrong prompt picked for a DocType | Industry‑specific row missing; falling back to Generic | Add the missing industry+DocType entry. |
| New row not selected | `Enabled` = 0 or wrong `Industry`/`Target DocType` | Tick `Enabled`; verify the DocType slug. |
| Seeder did not overwrite my edits | Built‑in seeder respects user edits | Call `seed_builtin_prompts(overwrite=True)`. |

---

## 12. Related DocTypes

- **IDP Prompt Template** — the Jinja‑rendered system prompt used by
  the live LLM agent loop. Use Prompt Library for the *gallery*, Prompt
  Template for the *active* prompt.
- **IDP Skill** — short reusable rule blocks appended after the prompt
  body.
- **IDP Extraction Template** — supplier‑specific mappings; orthogonal
  to the prompt.
