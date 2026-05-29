# IDP Prompt Template — User Manual

> **DocType:** `IDP Prompt Template`
> **Module:** IDP
> **Roles:** System Manager (full), IDP User (read‑only)
> **Auto‑name:** `field:template_name`
> **Menu path:** `/app/idp-prompt-template`

`IDP Prompt Template` is the **active, Jinja‑rendered system prompt**
used by the IDP LLM agent loop. Where `IDP Prompt Library` is a
catalogue / gallery, `IDP Prompt Template` is what actually drives the
LLM at runtime.

A template ships:

- A name (unique).
- Optional scoping by **Target DocType** and **Output Language**.
- A **Jinja‑templated system prompt** with placeholders such as
  `{{ doctype }}`, `{{ language }}`, `{{ company }}`, and any custom
  arguments you declare.
- A child table of **Arguments** declaring the variables the template
  expects (name, type, required flag, default value).

On save the controller compiles the Jinja syntax (no render) — a
template with a typo will refuse to save with a clear error.

The lookup cache is invalidated on every save and delete, so changes
take effect on the next conversation turn.

---

## 1. When to use this DocType

- Replace the legacy hard‑coded prompt with an editable one.
- Maintain different prompts per **Target DocType** (Purchase Invoice
  vs. Sales Invoice) or per **Output Language** (English vs. Hindi).
- Add custom Jinja variables (e.g. `{{ supplier }}`, `{{ tax_rate }}`)
  that the agent loop will fill in.
- Disable a prompt without deleting it (un‑tick `Enabled`).

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Template Name** | Data, unique | ✔ | Becomes the document name. Slug‑like, e.g. `purchase_invoice_en`. |
| **Enabled** | Check (default `1`) | — | Disable to keep the row but exclude it from `find_template`. |
| **Target DocType** | Link → DocType | — | Match the conversation's target DocType. **Empty = wildcard** (applies to any DocType). |
| **Output Language** | Data | — | Match the conversation's output language (e.g. `English`, `हिन्दी`). **Empty = wildcard**. |
| **Description** | Small Text | — | Free‑form notes. |
| **System Prompt** | Long Text | ✔ | Jinja‑templated prompt body. Validated on save. |
| **Arguments** (child table → IDP Prompt Template Argument) | Table | — | Declares the variables the template expects. |

### 2.1 Arguments child table

Each row describes one variable used in the Jinja body.

| Column | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Argument Name** | Data | ✔ | The variable name as used in Jinja (e.g. `supplier`). |
| **Type** | Select (`str`, `int`, `float`, `bool`, `list`, `dict`) | ✔ | Defaults to `str`. |
| **Required** | Check (default `0`) | — | When `1`, the renderer fails if the value is missing. |
| **Default Value** | Data | — | Used when the caller does not supply a value. |
| **Description** | Small Text | — | Documentation only. |

The framework always provides `doctype`, `language`, and `company` —
you only need to declare *additional* arguments.

---

## 3. Worked example — a Purchase Invoice prompt in English

```text
Template Name:   purchase_invoice_en
Enabled:         1
Target DocType:  Purchase Invoice
Output Language: English
Description:     PI extraction prompt, ERPNext-aware, ISO dates.
```

**System Prompt**

```jinja
You are an extraction assistant for {{ company or "the user's company" }}.
The active ERPNext DocType is **{{ doctype }}** and the desired output
language is **{{ language }}**.

{% if supplier %}
The supplier is **{{ supplier }}**. Prefer values that match this
supplier's known formats.
{% endif %}

Rules:
- Return ISO YYYY-MM-DD dates.
- Amounts are bare numbers without currency symbols.
- For missing fields, return null — never invent values.
- Map every line item separately.
- If a tax breakup (CGST / SGST / IGST) is present, populate each row
  in the taxes table individually.

Output the JSON envelope expected by the {{ doctype }} schema only —
no commentary.
```

**Arguments table**

| Argument Name | Type | Required | Default | Description |
| --- | --- | :---: | --- | --- |
| `supplier` | str | ✖ | — | Optional supplier name hint. |
| `company` | str | ✖ | — | Already auto‑injected; declared for documentation. |

When the conversation routes to *Purchase Invoice / English*, the
renderer will pick this template, fill the placeholders, and prepend
the result to the agent's tool descriptions and any matching
`IDP Skill` blocks.

---

## 4. Worked example — bilingual fallback

Goal: one wildcard template that works for any DocType, but in Hindi.

```text
Template Name:   default_hi
Enabled:         1
Target DocType:  (blank, wildcard)
Output Language: हिन्दी
```

**System Prompt**

```jinja
आप एक सटीक डेटा निष्कर्षण सहायक हैं। उपयोगकर्ता ने एक व्यावसायिक
दस्तावेज़ अपलोड किया है। लक्षित ERPNext DocType है **{{ doctype }}**।

नियम:
- तिथियाँ ISO YYYY-MM-DD में लौटाएँ।
- राशियाँ बिना मुद्रा प्रतीक के, केवल संख्या के रूप में लौटाएँ।
- मान केवल वही लौटाएँ जो दस्तावेज़ में हों — कुछ भी अनुमान न लगाएँ।
```

This row is selected only when the conversation's output language is
Hindi and **no** Hindi prompt with a tighter `Target DocType` exists.

---

## 5. Template selection algorithm

The selector lives in `idp.llm.prompt_templates.find_template`.
Pseudocode:

```text
For each enabled template:
    score = 0

    if template.target_doctype:
        if template.target_doctype == request.target_doctype: score += 2
        else:                                                  disqualify  # mismatch on a pinned target
    if template.language:
        if template.language == request.language:              score += 1
        else:                                                  disqualify  # mismatch on a pinned language

Sort by score desc.
Return the top row (or None when nothing matches / nothing is enabled).
```

Practical consequences:

- **Pinned beats wildcard**: a row with both `Target DocType` and
  `Output Language` always beats a wildcard match.
- **Mismatched pin disqualifies**: a Hindi‑only row will *not* be
  picked for an English conversation, even when nothing else matches.
- **Render failure ⇒ legacy prompt**: if Jinja rendering throws at
  runtime, the agent falls back to the legacy hard‑coded prompt — the
  user is never left without a prompt.

---

## 6. Render API (advanced)

For tests, REPL exploration, or custom pipelines you can render a
template directly:

```python
from idp.llm.prompt_templates import render_match, render

# Best-match lookup + render
text = render_match(
    target_doctype="Purchase Invoice",
    language="English",
    context={"supplier": "ACME Industries", "company": "Globex Ltd"},
)

# Render a specific template by name
text = render("purchase_invoice_en", context={
    "doctype": "Purchase Invoice",
    "language": "English",
    "supplier": "ACME Industries",
    "company": "Globex Ltd",
})
```

Both helpers return `None` when no template matches or rendering
fails — callers must handle that gracefully.

---

## 7. Lifecycle

1. **Create.** Pick a `Template Name`, write a Jinja `System Prompt`,
   declare the `Arguments` you reference.
2. **Save.** The controller compiles the Jinja AST. A syntax error
   throws *Invalid Jinja syntax in system prompt: …* without saving.
3. **Use.** The next conversation that scopes to your `Target DocType`
   + `Output Language` picks the template via `find_template`.
4. **Edit.** Save invalidates the template lookup cache; effective on
   the next turn.
5. **Disable.** Untick `Enabled` instead of deleting when you want to
   keep the row around.

---

## 8. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |
| IDP User | ✔ | ✖ | ✖ | ✖ |

Prompts are an administrative surface. End users read them indirectly
via the chatbot's *show system prompt* developer toggle.

---

## 9. Tips & best practices

- **Wildcard the universal floor.** Keep one row with no `Target
  DocType` and no `Language` — it becomes the catch‑all.
- **One template per (DocType, language).** Avoid two enabled rows with
  identical scoping; the selector is deterministic but humans get
  confused.
- **Keep prompts under ~ 1500 tokens.** Long prompts inflate cost on
  every turn. Push reusable rules into `IDP Skill` instead.
- **Lint Jinja locally.** The validator catches syntax, not logic —
  preview with `render_match(...)` before relying on a new template.
- **Always quote string defaults** in the Arguments table (e.g.
  `"INR"`, not `INR`) — defaults are stored as text.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| *Invalid Jinja syntax in system prompt: …* on save | Mismatched `{% %}`, missing endif, etc. | Fix the syntax — the error message points at the line. |
| Template not selected at runtime | `Enabled` = `0`, or a pinned `Target DocType`/`Language` mismatches the conversation | Re‑check the scopes and the `enabled` flag. |
| Render returns `None` | A required argument has no value and no default | Add a `default_value` in the Arguments table, or pass it from the caller. |
| Two templates compete for the same slot | Both have identical scopes | Disable one or pin the other tighter. |
| Changes don't show up | Cache hit on the previous body | Resave the template; the controller invalidates the cache on every save. |

---

## 11. Related DocTypes

- **IDP Prompt Library** — catalogue of reusable prompt bodies. Copy
  from the Library, paste into the System Prompt, then add Jinja.
- **IDP Skill** — markdown blocks appended *after* the prompt body and
  *before* the tool descriptions.
- **IDP Settings → LLM Configuration** — chooses which model receives
  the rendered prompt.
