# IDP Settings — User Manual

> **DocType:** `IDP Settings` (Single)
> **Module:** IDP
> **Required role:** System Manager
> **Menu path:** *Awesome Bar → "IDP Settings"* or `/app/idp-settings`

`IDP Settings` is the single configuration document that controls every
runtime behaviour of the Intelligent Document Processing (IDP) module —
which LLM provider is active, how OCR runs, how the chatbot UI behaves,
how long conversations are retained, and which token‑efficiency knobs
are enabled.

There is **one row only**. Changes take effect immediately for new
conversations; in‑flight conversations continue with the configuration
that was active when they started.

---

## 1. When to use this DocType

Open IDP Settings when you need to:

- Turn the whole IDP module on or off (kill switch).
- Switch the active LLM provider (OpenAI ↔ Anthropic ↔ Ollama) or
  change the model.
- Tune OCR behaviour (language, confidence threshold, file‑size caps).
- Configure the **two‑tier LLM router** (cheap model for gating,
  expensive model for extraction).
- Enable / disable advanced features: hybrid mapper, page pre‑pass,
  vision gating, transcript summarisation.
- Control chatbot UX flags: streaming, cost footer, suggested prompts,
  bulk actions.
- Set conversation retention and the post‑confirmation undo window.

---

## 2. Tab map

| Tab | Section | Purpose |
| --- | --- | --- |
| (header) | Chatbot UI · LLM Provider · LLM Configuration | Master switches and provider routing |
| **Document Processing** | OCR Configuration · Document Processing | OCR engine, languages, write‑mode |
| **Advanced** | Extraction Hardening · Advanced · Advanced Features | Engine internals, approver rules |
| **Hybrid Mapper** | Hybrid Mapper · Token‑Efficiency Deep Cuts · Provenance | LLM fallback, page pre‑pass, cache |
| **Conversation** | Conversation · Retention · Reversibility | UX flags, archive policy, undo window |

---

## 3. Field reference (by section)

### 3.1 Top — master switches

| Field | Type | Default | What it controls |
| --- | --- | --- | --- |
| **Enabled** | Check | `1` | Global kill switch. When `0`, all IDP API endpoints return *IDP disabled*. |
| **Streaming Enabled** | Check | `1` | Stream assistant prose token‑by‑token over Socket.IO. Disable in strict‑audit environments. |

### 3.2 LLM Provider

| Field | Type | Notes |
| --- | --- | --- |
| **LLM Provider** | Select (`openai` / `anthropic` / `ollama`) | The currently active provider. Only one is in use at a time. |
| **LLM Model** | Data | Model id passed to the provider, e.g. `gpt-4o-mini`, `claude-haiku-4-5-20251001`, `llama3.1:8b`. |
| **LLM API Key** | Password (encrypted) | API key for OpenAI / Anthropic. Ollama ignores this field. |
| **Ollama Host URL** | Data | Base URL of the Ollama HTTP server. Default `http://localhost:11434`. |
| **Custom Providers (JSON)** | Long Text | Register additional providers without code changes. Example below. |
| **Model Overrides (JSON)** | Long Text | Override model metadata (e.g. token cost, context window). Example below. |

**Custom Providers sample**

```json
[
  {"name": "azure", "module": "myapp.llm.azure", "class": "AzureProvider"},
  {"name": "vertex", "module": "myapp.llm.vertex", "class": "VertexProvider"}
]
```

**Model Overrides sample**

```json
{
  "gpt-4o-mini":       {"input_cost_per_1k": 0.00015, "output_cost_per_1k": 0.0006},
  "claude-haiku-4-5":  {"context_window": 200000}
}
```

### 3.3 LLM Configuration — two‑tier routing

| Field | Type | Notes |
| --- | --- | --- |
| **LLM Enabled** | Check (default `1`) | Master switch for the v2 LLM stack. Turn off to fall back to rule‑only extraction. |
| **LLM Model Routes** | Child table | One row per *purpose* mapping to provider / model / tier. |
| **LLM Max Output Tokens** | Int (default `16384`) | Cap on output tokens per response (Anthropic / OpenAI `max_tokens`, Ollama `num_predict`). Raise when long confirmation cards get truncated mid‑JSON. |

**Purposes**: `classification`, `extraction`, `vision`, `summarisation`,
`confirmation`. **Tier** is either `cheap` (gating) or `expensive`
(extraction).

**Sample route table**

| Purpose | Provider | Model | Tier |
| --- | --- | --- | --- |
| classification | anthropic | claude-haiku-4-5-20251001 | cheap |
| extraction | anthropic | claude-opus-4-5-20251101 | expensive |
| vision | ollama | minicpm-v:8b | cheap |
| summarisation | anthropic | claude-haiku-4-5-20251001 | cheap |
| confirmation | anthropic | claude-opus-4-5-20251101 | expensive |

> Each `purpose` must be unique within the table — the controller throws
> *Duplicate LLM model route for purpose 'X'* on save otherwise.

### 3.4 Document Processing → OCR Configuration

| Field | Default | Notes |
| --- | --- | --- |
| **Default OCR Language** | `en` | PaddleOCR language code used when a conversation does not pin its own. Set `auto` to detect per upload. |
| **Default Output Language** | `English` | Language used for confirmation cards, narrative fields, and chatbot replies. |
| **Confidence Threshold** | `0.70` | Minimum OCR confidence before a field is flagged for review (0.0 – 1.0). The controller rejects values outside that range. |
| **Enable Language Auto‑Detect** | `1` | Runs a fast detector pass on each upload when the conversation's OCR language is `auto`. |
| **Enable Table Extraction** | `1` | Extract tabular data via Paddle's structure model. |
| **Enable Layout Analysis** | `1` | Use layout boxes to keep multi‑column documents in reading order. |
| **Max File Size (MB)** | `25` | Maximum upload size. Must be > 0. |

### 3.5 Document Processing → Document Processing

| Field | Default | Notes |
| --- | --- | --- |
| **Enable Write Operations** | `0` | When **off**, the API never creates ERPNext documents (safe **dry‑run** mode). Turn on once you trust extraction quality in your environment. |
| **Auto‑create Missing Masters** | `0` | Auto‑create Supplier / Customer / Item masters that the document references but do not exist. Combine with master review queues. |
| **Enable Comparison** | `1` | Allow `compare_document` to dedupe before creation. |

### 3.6 Advanced → Extraction Hardening

| Field | Default | Notes |
| --- | --- | --- |
| **OCR Engine** | `auto` | `paddle` = PaddleOCR; `ollama_vision` = LLaVA / minicpm‑v fallback; `auto` = paddle then fall back on OCRError. |
| **Inline Text Budget (chars)** | `12000` | Maximum characters of OCR text inlined in tool results before truncation. |
| **Vision Image Max Dim (px)** | `1568` | Vision OCR resizes images down to this dimension before sending to Ollama (controls token cost). |

### 3.7 Advanced → Advanced

| Field | Default | Notes |
| --- | --- | --- |
| **OCR Timeout (seconds)** | `300` | Wall‑clock timeout for the PaddleOCR subprocess. Expiry returns `OCR_TIMEOUT`. Must be > 0. |
| **Confirmation Card Page Size** | `10` | Default rows per page on the ConfirmationCard items table. Range 5 – 50. |
| **Max Pages per PDF** | `100` | Stop OCR after N pages. Files exceeding this cap raise `PDF_TOO_MANY_PAGES`. Must be > 0. |

### 3.8 Advanced → Advanced Features

| Field | Notes |
| --- | --- |
| **Approver Rules (JSON)** | JSON array of approver rules per DocType. Consumed by the workflow router. |

**Approver Rules sample**

```json
[
  {"doctype": "Purchase Invoice", "amount_above": 100000, "approver_role": "Finance Manager"},
  {"doctype": "Purchase Invoice", "amount_above":      0, "approver_role": "Accounts User"},
  {"doctype": "Sales Invoice",    "amount_above":  50000, "approver_role": "Sales Manager"}
]
```

### 3.9 Hybrid Mapper → Hybrid Mapper

| Field | Default | Notes |
| --- | --- | --- |
| **Enable Hybrid Mapper** | `0` | Run the LLM‑backed hybrid mapper for low‑confidence extractions. |
| **Enable Pre‑Validation** | `1` | Run schema pre‑validation before sending docs to the LLM extraction loop. Disable to let the agent run unconstrained. |

### 3.10 Hybrid Mapper → Token‑Efficiency Deep Cuts

| Field | Default | Notes |
| --- | --- | --- |
| **Page Pre‑Pass Enabled** | `1` | Pages without a recognised signal (amount, date, GSTIN, IFSC, account no., invoice no.) are replaced with a placeholder in the LLM context. Originals remain in storage. |
| **Mapper Output Cache Enabled** | `1` | Cache hybrid‑mapper output keyed by *(file_hash, target_doctype, mapper_version)*. Re‑uploading the same bytes within TTL skips both the rule pass and the LLM when confidence is sufficient. |
| **Mapper Cache TTL (hours)** | `24` | TTL for the cache above. `0` disables the cache. |
| **Vision Text Threshold (chars)** | `200` | Vision gating: vision is invoked only when pypdf‑extracted text length falls below this count (or alphanumeric ratio < 5%). `0` always runs vision. |
| **Summarise After N Messages** | `8` | Sliding‑window summariser — older messages are compressed into a digest via the cheap tier once the conversation passes this length. `0` disables. |
| **Strip Thinking Blocks** | `1` | Strip Anthropic extended‑thinking blocks from prior turns when rebuilding context. Originals stay in `IDP Message` for replay. |
| **Mapper Version** | `1` | Bump manually when the rule‑mapper schema changes. Forms part of the cache key so stale entries are evicted on schema bumps. |
| **TE Regression Alert (%)** | `15` | Weekly metrics threshold — when `tokens_per_extracted_field` rises by more than this percent versus the prior 7‑day window, an Email Alert is sent. |

### 3.11 Hybrid Mapper → Provenance & Confidence Surface

| Field | Default | Notes |
| --- | --- | --- |
| **Show Confidence Dots** | `0` | Render green / amber / red dots in ConfirmationCard line items. Header fields never render dots; this flag only affects child‑table rows. |

### 3.12 Conversation → Conversation

| Field | Default | Notes |
| --- | --- | --- |
| **Enable Cost Footer** | `1` | Show a persistent cost / tokens / duration chip at the bottom of the chat. |
| **Enable Pre‑flight Cost Warning** | `0` | Open a confirmation dialog before high‑cost turns. |
| **Enable Suggested Prompts** | `1` | Show three suggested prompt chips above the composer on empty conversations. |
| **Enable Sidebar Search** | `1` | Show search box and filter chips on the sidebar. |
| **Enable Bulk Card Actions** | `1` | Render bulk‑action header when a single turn yields ≥ 3 confirmation cards. |
| **Enable Conversation Delete** | `1` | Allow users to delete conversations from the sidebar. When off, only archive is available. |

### 3.13 Conversation → Retention

| Field | Default | Notes |
| --- | --- | --- |
| **Active Retention (days)** | `90` | Active conversations are auto‑archived after N days. `0` disables the auto‑archive job. |

### 3.14 Conversation → Reversibility

| Field | Default | Notes |
| --- | --- | --- |
| **Undo Window (minutes)** | `5` | Window after card confirmation during which the originating user (or a System Manager) can undo the created ERPNext document. Drafts are deleted, submittable documents are cancelled. Set `0` to disable end‑to‑end. |

---

## 4. End‑to‑end setup walk‑through

A first‑time admin typically completes these steps once:

**Step 1 — flip the master switch on**

1. Open `/app/idp-settings`.
2. Tick **Enabled**.

**Step 2 — choose your LLM provider**

1. Scroll to *LLM Provider*.
2. Set **LLM Provider** = `anthropic` (or `openai`, `ollama`).
3. Paste the API key into **LLM API Key**.
4. Set **LLM Model** to the production model you want as the default,
   e.g. `claude-opus-4-5-20251101`.

**Step 3 — wire up two‑tier routing**

1. Add five **LLM Model Routes** rows — one per purpose
   (classification, extraction, vision, summarisation, confirmation).
2. Use the sample table in §3.3 as a starting point.

**Step 4 — tune OCR for your locale**

1. Open the **Document Processing** tab.
2. Set **Default OCR Language** (e.g. `en`, `hi`, `auto`).
3. Set **Default Output Language** (e.g. `English`, `हिन्दी`).
4. Leave **Confidence Threshold** at `0.70` until you have real data.

**Step 5 — pick a safe rollout mode**

1. Leave **Enable Write Operations** = `0` for the first week — every
   extraction is reviewed but no ERPNext docs are created.
2. After confidence is established, flip it to `1` and optionally enable
   **Auto‑create Missing Masters**.

**Step 6 — turn on token‑efficiency features**

For a cost‑aware roll‑out, enable in this order:

1. **Page Pre‑Pass Enabled** — usually saves 30 – 60 % of tokens.
2. **Mapper Output Cache Enabled** with TTL 24 h.
3. **Summarise After N Messages** = `8`.
4. **Strip Thinking Blocks** = `1` (Anthropic users).

**Step 7 — set retention & reversibility**

1. **Active Retention (days)** = `90` (or per your compliance policy).
2. **Undo Window (minutes)** = `5` for a polite safety net; raise to
   `30` for cautious teams.

**Step 8 — save**.

Cache invalidation is automatic; no worker restart is needed.

---

## 5. Common scenarios

### 5.1 Move from OpenAI to Anthropic

1. Update **LLM Provider** = `anthropic`.
2. Update **LLM API Key** and **LLM Model** (e.g. `claude-opus-4-5-20251101`).
3. Replace each **LLM Model Routes** row's provider/model.
4. Save.

In‑flight conversations continue with the old provider; new turns use
the new one.

### 5.2 Dry‑run pilot

- **Enable Write Operations** = `0`
- **Enable Pre‑Validation** = `1`
- **Show Confidence Dots** = `1`
- **Enable Pre‑flight Cost Warning** = `1`

Users see ConfirmationCards and confidence dots, but no ERPNext records
are created.

### 5.3 Air‑gapped / local‑only deployment

- **LLM Provider** = `ollama`
- **Ollama Host URL** = the local server
- **OCR Engine** = `paddle` (or `auto`)
- **Streaming Enabled** = `0` if Socket.IO is restricted

### 5.4 Cost emergency — clamp tokens

1. Set **LLM Max Output Tokens** = `4096`.
2. Set **Inline Text Budget (chars)** = `6000`.
3. Set **Vision Text Threshold** = `400` (forces vision off whenever
   pypdf returns a reasonable text layer).
4. Save.

### 5.5 Audit‑strict configuration

- **Streaming Enabled** = `0`
- **Strip Thinking Blocks** = `0` (keep full LLM trace)
- **Enable Conversation Delete** = `0`
- **Undo Window (minutes)** = `0`
- **Active Retention (days)** = `0`

---

## 6. Validation rules

The controller throws a hard error on save when:

- `Confidence Threshold` is outside `[0.0, 1.0]`.
- `Max File Size (MB)`, `OCR Timeout (seconds)`, or
  `Max Pages per PDF` is ≤ 0.
- `Active Retention (days)` is negative.
- The **LLM Model Routes** table contains two rows with the same
  `purpose`.

---

## 7. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |

End users (`IDP User`) never see this DocType.

---

## 8. Related DocTypes

- **IDP Prompt Template** — admin‑defined system prompts.
- **IDP Skill** — markdown rules appended to the prompt.
- **IDP Extraction Template** — per‑DocType field mappings and
  confidence overrides.
- **IDP Tool Configuration** — per‑tool enable/role overrides.
- **IDP Plugin Configuration** — per‑plugin toggle.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| *IDP disabled* error from every endpoint | **Enabled** is off | Tick **Enabled** and save. |
| Extraction always falls back to rules only | **LLM Enabled** = off, or no API key | Enable LLM, paste key, save. |
| Confirmation cards truncated mid‑JSON | Output token cap too low | Raise **LLM Max Output Tokens** to ≥ 32000. |
| Vision called on every upload | **Vision Text Threshold** = 0 | Set to 200 – 400. |
| Saves throw "Duplicate LLM model route" | Two rows share the same purpose | Remove the duplicate or change its purpose. |
| OCR fails silently for one language | Language not in PaddleOCR list | Set **Default OCR Language** = `auto`. |
