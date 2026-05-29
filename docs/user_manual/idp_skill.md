# IDP Skill — User Manual

> **DocType:** `IDP Skill`
> **Module:** IDP
> **Roles:** System Manager (full), IDP User (read‑only)
> **Auto‑name:** `field:skill_name`
> **Menu path:** `/app/idp-skill`

`IDP Skill` is a **short, focused markdown block** appended to the
LLM system prompt for matching conversations. Skills are intentionally
separate from `IDP Prompt Template` so a single template can reuse
rules shared across multiple DocTypes (e.g. a *VAT compliance* skill
used by both Sales Invoice and Purchase Invoice templates).

A skill ships:

- A name (unique).
- Optional scoping by **Target DocType** and **Output Language**.
- A markdown body that becomes part of the prompt.

The agent assembles the final system prompt as:

```
<rendered IDP Prompt Template body>

### Extraction Skills

**<Skill A name>**
<Skill A markdown>

**<Skill B name>**
<Skill B markdown>

<tool descriptions>
```

Skills are cached for 5 minutes; saves / deletes invalidate the cache.

---

## 1. When to use this DocType

- Codify a **reusable extraction rule** that applies across multiple
  prompts (date formats, GSTIN regex, HSN code length, rounding).
- Provide **worked examples** that should not bloat every prompt
  template.
- Maintain **per‑language guidance** (e.g. how to handle Devanagari
  numerals) without forking the prompt template.
- Turn a rule on/off across the whole system with one switch.

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Skill Name** | Data, unique | ✔ | Becomes the document name. Slug‑like, e.g. `vat_compliance_in`. |
| **Enabled** | Check (default `1`) | — | Disable to hide the skill from the assembler without deleting it. |
| **Target DocType** | Link → DocType | — | Match the conversation's target DocType. **Empty = wildcard** (any DocType). |
| **Output Language** | Data | — | Match the conversation's language. **Empty = wildcard**. |
| **Description** | Small Text | — | Free‑form notes. |
| **Markdown Content** | Long Text | ✔ | The markdown block appended to the system prompt. |

---

## 3. Matching rules

The assembler walks every enabled skill and applies this filter:

```text
if skill.target_doctype and skill.target_doctype != request.doctype:  skip
if skill.language       and skill.language       != request.language: skip
otherwise:                                                            include
```

Practical consequences:

- A skill with both fields blank is a **global** skill — included on
  every conversation.
- A skill pinned to `Purchase Invoice` is included only for Purchase
  Invoice conversations regardless of language.
- A skill pinned to `English` is included only for English
  conversations regardless of DocType.
- Multiple skills can match — they are all concatenated, separated by
  blank lines, under a single `### Extraction Skills` header.

---

## 4. Worked example — Indian GST compliance (DocType‑specific)

```text
Skill Name:      gst_india_purchase_invoice
Enabled:         1
Target DocType:  Purchase Invoice
Output Language: (blank, any language)
Description:     India GST handling for vendor bills.
```

**Markdown Content**

```markdown
### India — GST Handling

- **GSTIN** is a 15‑character alphanumeric: `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9][A-Z][0-9A-Z]$`.
  Place it in `tax_id` on the supplier record and `bill_gstin` on the
  Purchase Invoice header when both are present.
- Tax rows must populate one row each for **CGST**, **SGST**, and
  **IGST** when shown separately. Do not merge.
- **HSN/SAC** codes are 4 to 8 digits. Place them on the corresponding
  line item, not the header.
- **TCS / TDS** lines belong in the `taxes` table with a positive
  rate and a negative amount when collected at source.
- A **reverse charge** flag (`reverse_charge`) is `1` when the
  document carries an explicit RCM note.
```

---

## 5. Worked example — universal date / number formatting (global)

```text
Skill Name:      common_formatting
Enabled:         1
Target DocType:  (blank, any DocType)
Output Language: (blank, any language)
```

**Markdown Content**

```markdown
### Universal Formatting

- **Dates** — always emit `YYYY-MM-DD`. Convert from any locale
  (`13/01/2026`, `13-Jan-2026`, `१३-०१-२०२६`) before output.
- **Amounts** — bare numbers, no currency symbol, no thousands
  separator. Use `.` for the decimal point.
- **Percentages** — emit as a number (e.g. `9` for 9%), never as
  `"9%"` or `0.09`.
- **Missing values** — emit `null`, never `""`, never `"N/A"`.
```

This row is included in **every** assembly because both scope fields
are blank.

---

## 6. Worked example — Hindi number normalisation (language‑specific)

```text
Skill Name:      devanagari_numbers
Enabled:         1
Target DocType:  (blank)
Output Language: हिन्दी
```

**Markdown Content**

```markdown
### देवनागरी अंकों का सामान्यीकरण

- दस्तावेज़ में आये देवनागरी अंक (०-९) हमेशा ASCII अंकों (0-9) में
  परिवर्तित करें।
- राशियों में पूर्णांक / दशमलव बिंदु अपरिवर्तित रखें — केवल अंक बदलें।
- तिथियाँ ISO `YYYY-MM-DD` फ़ॉर्मेट में लौटाएँ।
```

This skill is included only when the conversation's output language
is Hindi, regardless of DocType.

---

## 7. Inspect what got appended

Use the Python helper for ad‑hoc inspection:

```python
from idp.llm.skills import get_skills_block

block = get_skills_block(target_doctype="Purchase Invoice", language="English")
print(block)
# → "### Extraction Skills\n\n**gst_india_purchase_invoice**\n\n...\n\n**common_formatting**\n\n..."
```

Returns an empty string when no skills match.

---

## 8. Lifecycle

1. **Create.** Give it a slug‑like name, scope as wide or narrow as
   you need, write markdown.
2. **Save.** The 5‑minute lookup cache is invalidated, so the new
   skill participates in the next conversation turn.
3. **Edit / Disable / Delete.** Each invalidates the cache.
4. **Promote.** Skills that prove themselves over time can be
   referenced from your `IDP Prompt Template` body directly — that
   bakes the rule in at the template level.

---

## 9. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |
| IDP User | ✔ | ✖ | ✖ | ✖ |

Skills are admin‑curated. End users only see the *effect* of a skill
in the assistant's behaviour.

---

## 10. Tips & best practices

- **One concept per skill.** A skill should answer a single question
  ("How do I format dates?", "How does VAT work in India?"). Split
  multi‑topic skills into multiple rows.
- **Keep them under ~ 400 tokens.** Skills are appended on every
  matching turn — long skills are a recurring cost.
- **Wildcard sparingly.** Each wildcard skill is added to *every*
  conversation. Reserve wildcards for true universals (dates,
  amounts, null handling).
- **Prefer DocType scoping over language scoping** when in doubt — a
  good prompt template should already cover language style.
- **Test by inspection.** Call `get_skills_block(...)` after each
  edit to confirm only the intended skills are concatenated.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Skill never appears in the prompt | `Enabled` = `0`, or pinned scope mismatches | Tick `Enabled`; recheck `Target DocType` / `Output Language`. |
| Two skills duplicate the same rule | Overlapping wildcard + pinned skill | Narrow the wildcard or remove one. |
| Prompt becomes too long after enabling many skills | Each match adds to the prompt body | Disable the least‑specific ones or move rules into the Prompt Template body. |
| Recent edit not visible to the LLM | Cache hit on the previous body | Resave the skill (or any skill) — invalidates the cache. |
| `get_skills_block` returns `""` | No enabled skills match the requested scope | Add at least one matching skill (or a wildcard one). |

---

## 12. Related DocTypes

- **IDP Prompt Template** — the Jinja base prompt. Skills are appended
  to its rendered output.
- **IDP Prompt Library** — long‑form prompt gallery. Use the Library
  for full prompts, Skills for small reusable rules.
- **IDP Extraction Template** — supplier‑specific mappings; orthogonal
  to skills.
