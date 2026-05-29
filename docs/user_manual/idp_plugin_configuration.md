# IDP Plugin Configuration — User Manual

> **DocType:** `IDP Plugin Configuration`
> **Module:** IDP
> **Roles:** System Manager (only)
> **Auto‑name:** `field:plugin_name`
> **Sort:** by `priority` ascending
> **Menu path:** `/app/idp-plugin-configuration`

`IDP Plugin Configuration` is the **runtime registry** for IDP plugins.
A plugin bundles a set of tools (and optionally prompt templates and
skills) under a single namespace. Third‑party Frappe apps register
plugins via `hooks.py`:

```python
# In any installed app's hooks.py
idp_plugins = "myapp.idp_integration:MyAppPlugin"
# …or a tool-only hook:
idp_tools   = "myapp.idp_integration.get_tools"
```

Discovered plugins automatically get a row in this DocType. The row
lets admins:

- Enable / disable the entire plugin (and all its tools) with one
  click.
- Control the **load order** via `priority` (lower = earlier).
- Read the plugin's declared `version` and `description`.
- Hand the plugin its own `JSON` configuration blob (consumed by the
  plugin's own settings layer).

Every save / delete invalidates the plugin discovery cache and the
tool registry cache, so changes propagate without a worker restart.

---

## 1. When to use this DocType

- Disable a plugin while debugging — instead of removing the
  installed app.
- Reorder plugins so a domain plugin (e.g. *acme_logistics*) loads
  before *core* and overrides a tool.
- Pass per‑plugin configuration (API endpoints, feature flags) without
  touching `site_config.json` or the plugin's own DocType.
- Inspect the plugin's declared version after an upgrade.

---

## 2. Field reference

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| **Plugin Name** | Data, unique | ✔ | Slug matching `IDPPlugin.name` (e.g. `core`, `acme_logistics`). Becomes the document name. |
| **Display Name** | Data | — | Human‑readable label shown in the admin UI. |
| **Enabled** | Check (default `1`) | — | When `0`, none of the plugin's tools, templates, or skills are loaded. |
| **Priority** | Int (default `100`) | — | Lower numbers load first; ties resolved by plugin name. |
| **Version** | Data, read‑only | — | SemVer string declared by the plugin class. Updated automatically. |
| **Description** | Small Text, read‑only | — | One‑line summary from the plugin class. |
| **Config (JSON)** | JSON | — | Free‑form JSON consumed by the plugin's own settings layer. |

---

## 3. How a plugin reaches this DocType

1. A Frappe app declares the plugin via `hooks.py`:

   ```python
   idp_plugins = "acme_logistics.idp:AcmeLogisticsPlugin"
   ```

2. After `bench migrate`, the IDP loader discovers the class and
   auto‑creates a row in `IDP Plugin Configuration` with
   `Enabled = 1`, `Priority = 100`, and the plugin's `version` /
   `description` filled in.

3. The plugin contributes:
   - **Tools** via `get_tools()` — each tool also gets a default row
     in `IDP Tool Configuration`.
   - Optionally, **prompt templates** and **skills** stored under
     normal DocType rows.

4. Admins decide whether to leave the plugin enabled.

---

## 4. Sample records

### 4.1 The built‑in `core` plugin

```text
Plugin Name:   core
Display Name:  IDP Core
Enabled:       1
Priority:      0
Version:       1.0.0      (read-only)
Description:   Core IDP tools: extract, create, compare, delete, …
Config (JSON): {}
```

`core` is shipped with the IDP app. Keep it enabled and at a low
priority (typically `0`) so it loads first.

### 4.2 A third‑party plugin (Acme Logistics)

```text
Plugin Name:   acme_logistics
Display Name:  Acme Logistics — Delivery Tools
Enabled:       1
Priority:      50
Version:       2.3.1      (read-only)
Description:   Adds delivery_note extraction tuned for Acme.
```

**Config (JSON)**

```json
{
  "api_base_url": "https://api.acme.example.com/v1",
  "default_warehouse": "ACME-WH-DEL-01",
  "feature_flags": {
    "auto_split_shipments": true,
    "ml_assisted_packing":   false
  },
  "tracking_provider": "acme-track"
}
```

The plugin's own runtime reads this blob via the IDP plugin loader and
applies it to its tool behaviour — *no code change required to flip a
flag*.

### 4.3 A disabled / paused plugin

```text
Plugin Name:   sandbox_experiments
Display Name:  Sandbox Experiments
Enabled:       0
Priority:      999
Version:       0.4.0
Description:   Internal experiments. Do not enable in production.
Config (JSON): {"diagnostic_mode": true}
```

Because `Enabled = 0`, none of this plugin's tools are dispatchable
and none of its prompts/skills surface in the assembler.

### 4.4 An anonymous tool‑only plugin

When an app uses the `idp_tools` hook instead of `idp_plugins`, the
loader wraps its tools in an anonymous plugin and you'll see a row
like:

```text
Plugin Name:   anonymous_<app_name>
Display Name:  (blank)
Enabled:       1
Priority:      100
Version:       0.0.0
Description:   Tools-only hook from <app_name>
```

The anonymous wrapper exists purely so the per‑plugin toggle still
applies to those tools.

---

## 5. Load‑order rules

The loader produces a deterministic plugin list:

1. **Core first** (priority `0` by default).
2. All third‑party plugins sorted by `priority` ascending.
3. Ties resolved by `plugin_name` alphabetical.
4. Disabled rows skipped.
5. Plugins whose `is_available()` returns `False` are skipped (e.g.
   when an optional Python dependency is missing).

When two plugins contribute a tool with the same name, the **later**
plugin in the list shadows the earlier one — so giving a domain
plugin a *higher* priority value (later in the list) lets it override
a core tool.

---

## 6. End‑to‑end workflow — adopting a third‑party plugin

1. Install the third‑party app (`bench get-app …`, `bench install-app
   …`).
2. Run `bench migrate`. The IDP loader discovers
   `acme_logistics.idp:AcmeLogisticsPlugin` from its `hooks.py`.
3. A new row appears at `/app/idp-plugin-configuration/acme_logistics`
   with `Enabled = 1`.
4. Tune the `Priority` so it loads *after* `core` (e.g. `50`).
5. Fill in **Config (JSON)** with the plugin's runtime settings.
6. Save. Caches invalidate; tools become callable on the next agent
   dispatch.
7. (Optional) Open `/app/idp-tool-configuration` to fine‑tune the
   tools the plugin contributed (role gates, confirmation, token
   caps).

---

## 7. Permissions

| Role | Read | Write | Create | Delete |
| --- | :---: | :---: | :---: | :---: |
| System Manager | ✔ | ✔ | ✔ | ✔ |

End users (`IDP User`) cannot view this DocType.

---

## 8. Cache invalidation

Every save / delete invalidates `invalidate_plugin_cache()`, which in
turn rebuilds the plugin list **and** the tool registry on the next
lookup. Tool‑configuration caches are also flushed (transitively),
because tool availability depends on plugin availability.

This makes `IDP Plugin Configuration` safe to toggle in production —
no `bench restart`, no Socket.IO reconnect.

---

## 9. Tips & best practices

- **Don't disable `core`.** Most other plugins assume the core tools
  exist. Disable individual tools via `IDP Tool Configuration`
  instead.
- **Keep core at priority `0`.** Override semantics are clearest when
  `core` loads first and domain plugins override it later.
- **Use the JSON config, not site_config.** Plugin authors should
  always read from `IDP Plugin Configuration.config_json` so admins
  can edit settings from the UI.
- **Document the JSON schema** in your plugin's README — there is no
  JSON Schema enforcement here.
- **Read `Version` after upgrades** to confirm the new plugin code is
  loaded.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Plugin row missing after install | The app does not declare `idp_plugins` / `idp_tools` in `hooks.py` | Confirm the hook is exported; rerun `bench migrate`. |
| Tools still callable after `Enabled = 0` | Long‑running worker holds an old registry | Resave the row to force cache invalidation, or restart the worker. |
| Wrong plugin wins on overlapping tool names | Priority order inverted | Lower (earlier) priority loads first; later plugins shadow earlier ones, so give the *winner* a higher priority. |
| `Config (JSON)` edits ignored | Plugin reads from a different source (e.g. site_config) | Update the plugin to read `IDP Plugin Configuration.config_json`. |
| `Version` stays at `0.0.0` | Plugin class is `IDPPlugin` direct (no version attribute) | Set `version = "x.y.z"` on the plugin class. |
| Plugin shows `Enabled = 1` but no tools appear | `is_available()` returned `False` (missing optional dep) | Install the missing Python dep or implement `is_available()` correctly. |

---

## 11. Related DocTypes

- **IDP Tool Configuration** — per‑tool admin overrides. Use this for
  fine‑grained role gates *within* a plugin.
- **IDP Settings** — global settings inherited by every plugin.
- **IDP Prompt Template / IDP Skill** — plugins may ship templates and
  skills; they live in those DocTypes normally and obey the per‑plugin
  enable flag.
