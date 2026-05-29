# IDP Tool Configuration — User Manual

> **DocType:** `IDP Tool Configuration`
> **Module:** IDP
> **Roles:** System Manager (only)
> **Auto‑name:** `field:tool_name`
> **Sort:** by `tool_name` ascending
> **Menu path:** `/app/idp-tool-configuration`

`IDP Tool Configuration` is the **admin override layer** for every
tool the IDP agent can call (extract, create, compare, delete,
resolve_masters, ask_user, …). Each in‑code tool ships with a
default `ToolSpec` (its name, whether it is *mutating*, the role it
requires, the schema). This DocType lets you, at runtime:

- Turn an individual tool on or off.
- Force user confirmation before the tool result is accepted.
- Cap the output tokens the LLM may spend producing the result.
- Allow / deny the tool to specific roles.
- Annotate why an override exists.

When no row exists for a tool the in‑code `ToolSpec` defaults apply,
so the feature is **fully non‑breaking** — overrides are opt‑in.

Saves and deletes invalidate three caches (tool config, tool registry,
plugin registry) so changes propagate without a worker restart.

---

## 1. When to use this DocType

- Hide an experimental tool (`enabled = 0`) without a code change.
- Restrict a destructive tool (`delete_document`, `submit_document`)
  to a narrow role like *Finance Manager* — even if the in‑code spec
  is more permissive.
- Force a confirmation step on a tool that does not need one by
  default (e.g. `update_document`).
- Cap output tokens on a chatty tool to keep cost predictable.
- Document why a tool is enabled or disabled (audit‑friendly notes).

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Tool Name** | Data, unique | ✔ | Slug matching `ToolSpec.name` (e.g. `extract_document`, `create_document`, `compare_document`). Becomes the document name. |
| **Plugin** | Data | — | Plugin namespace that owns the tool. Used for filtering only. |
| **Enabled** | Check (default `1`) | — | When `0`, the tool is hidden from the LLM and rejected if called. |
| **Requires User Confirmation** | Check (default `0`) | — | When `1`, the tool result must carry `user_confirmed = True` before it is accepted. The typical use case is `create_document`. |
| **Mutating** | Check (read‑only) | — | Mirrors `ToolSpec.mutating` for filtering; set by the registry, not by hand. |
| **Max Output Tokens** | Int (non‑negative) | — | Per‑tool cap on LLM output tokens generated while producing the tool response. Blank or `0` = provider default. Exceeding the cap returns a `stop_processing` envelope with a friendly message. |
| **Allowed Roles** | Table → IDP Tool Role | — | Caller must hold at least one of these roles. **Empty = inherit `ToolSpec.requires_role` / open to all IDP users.** |
| **Denied Roles** | Table → IDP Tool Role | — | Caller holding **any** of these roles is rejected regardless of `Allowed Roles`. |
| **Admin Notes** | Small Text | — | Free‑form. Use it to record why an override exists. |

---

## 3. Role access logic

Resolution order at dispatch time:

1. **Tool disabled?** If `Enabled = 0`, reject immediately.
2. **Deny first.** If the caller holds any role in `Denied Roles`,
   reject.
3. **Allow list.** If `Allowed Roles` is non‑empty, the caller must
   hold at least one of those roles. Otherwise reject.
4. **Allow list empty?** Fall back to the in‑code
   `ToolSpec.requires_role` (or open to all IDP users when the spec
   has none).
5. **Confirmation gate.** If `Requires User Confirmation = 1`, the
   result envelope must contain `user_confirmed = True`. Otherwise the
   dispatcher pauses and asks the user.
6. **Token cap.** When `Max Output Tokens > 0`, the provider call is
   capped at that value. Overshoot ⇒ `stop_processing` envelope.

---

## 4. Sample records

### 4.1 Force confirmation on `create_document` (low‑risk default)

```text
Tool Name:                  create_document
Plugin:                     core
Enabled:                    1
Requires User Confirmation: 1
Mutating:                   1   (read-only mirror of the ToolSpec)
Max Output Tokens:          (blank — use provider default)
```

| Allowed Roles | Denied Roles |
| --- | --- |
| IDP User | — |
| Accounts User | — |

**Admin Notes**

```
Confirmation required because ConfirmationCard already shows the
user the exact payload — the dispatcher should never auto-commit.
```

### 4.2 Restrict `delete_document` to a single role

```text
Tool Name:                  delete_document
Plugin:                     core
Enabled:                    1
Requires User Confirmation: 1
Max Output Tokens:          0
```

| Allowed Roles |
| --- |
| Finance Manager |

| Denied Roles |
| --- |
| Guest |
| IDP User |

**Admin Notes**

```
Hard-restricted: only Finance Manager may delete via the chatbot.
Customer-success requested Aug-2026.
```

### 4.3 Disable an experimental tool

```text
Tool Name:                  experimental_summarise_invoice
Plugin:                     acme_logistics
Enabled:                    0
Max Output Tokens:          0
```

**Admin Notes**

```
Pending QA sign-off. Re-enable after release v1.4.
```

### 4.4 Cap output on a chatty tool

```text
Tool Name:                  compare_document
Enabled:                    1
Requires User Confirmation: 0
Max Output Tokens:          4096
```

When the LLM tries to generate more than 4096 tokens explaining the
comparison, dispatch returns a `stop_processing` envelope and the chat
shows the user a friendly *"Comparison was too long to render"*
message.

---

## 5. End‑to‑end workflow — locking down `create_document`

1. **Open the tool list.** Bench restart is not required; the registry
   auto‑discovers every in‑code tool.
2. **Create a row.** `New → IDP Tool Configuration`.
3. **Tool Name** = `create_document`. Choose from the registered tool
   names. The slug must match exactly.
4. **Plugin** = `core` (so admins can filter by plugin).
5. Tick **Requires User Confirmation**.
6. In **Allowed Roles**, add `IDP User` and `Accounts User`.
7. In **Denied Roles**, add `Guest`.
8. Set **Max Output Tokens** = `8000` (cap defensive padding).
9. Write a short **Admin Note**.
10. Save.

The override takes effect on the very next agent dispatch — caches are
invalidated automatically by the controller.

---

## 6. Listing and discovering tool names

Tool names come from the in‑code `ToolSpec.name`. To enumerate them:

```python
from idp.tools.registry_cache import get_cached_registry

registry = get_cached_registry()
for spec in registry.values():
    print(spec.name, "mutating=", spec.mutating, "role=", spec.requires_role)
```

Common core tool names (subject to change as the registry grows):

- `extract_document`
- `create_document`
- `compare_document`
- `delete_document`
- `resolve_masters`
- `find_matching_record`
- `ask_user`

Use these slugs verbatim in **Tool Name**.

---

## 7. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |

End users (`IDP User`) cannot view this DocType — it is admin‑only.

---

## 8. Cache invalidation

Every save / delete of an `IDP Tool Configuration` row invalidates:

- the per‑tool override cache (`invalidate_tool_config_cache(tool_name)`),
- the tool registry cache (`invalidate_tool_registry_cache()`),
- the plugin discovery cache (`invalidate_plugin_cache()`).

This means an admin can change a role gate or toggle `Enabled` and the
**next** LLM turn picks it up — no `bench restart` required.

---

## 9. Tips & best practices

- **Default to deny‑by‑role for mutating tools.** Force a narrow
  `Allowed Roles` list on anything with `Mutating = 1`. The
  `Mutating` flag is a great filter in the list view.
- **Don't put humans in `Denied Roles` you also expect to use the
  tool.** Deny wins, so a *"Sales User"* in both lists is denied.
- **Use Admin Notes for audit trails.** Future‑you will be grateful
  when a tool is mysteriously off.
- **Pair with IDP Plugin Configuration.** Disabling an entire plugin
  is cleaner than disabling each of its tools individually.
- **Per‑tool token caps are the cheapest cost control.** A 4k cap on a
  chatty tool can shave 10‑30 % off conversation cost.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tool still works after `Enabled = 0` | Cache hit in a long‑running worker | Resave the row to force invalidation. |
| User cannot call a tool they "should" be allowed to | Caller is also in `Denied Roles` (deny wins) | Remove them from the deny list. |
| Tool ignores `Max Output Tokens` | Value is `0` or blank | Set to a positive integer. |
| `stop_processing` returned unexpectedly | Token cap too tight | Raise `Max Output Tokens`. |
| Saved row but the slug does not match any tool | Typo in `Tool Name` | Pull the live registry via `get_cached_registry()` and copy the exact slug. |

---

## 11. Related DocTypes

- **IDP Plugin Configuration** — turn a whole plugin (set of tools)
  on or off at once.
- **IDP Tool Role** — child table; one row = one Frappe Role.
- **IDP Settings → LLM Max Output Tokens** — the global cap; per‑tool
  caps override the global when set.
