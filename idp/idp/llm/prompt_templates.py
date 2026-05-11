# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Admin-editable prompt templates (Phase 26 §26.4).

Resolves the best-matching ``IDP Prompt Template`` row for a given
``(target_doctype, language)`` pair and renders it via Jinja2.

Resolution preference (most specific first)::

    1. exact match on (template_name) when an explicit name is given,
    2. (target_doctype, language) both match and equal the context,
    3. target_doctype matches; language empty,
    4. language matches; target_doctype empty,
    5. both fields empty (generic fallback).

A render failure falls back to the legacy hard-coded chat prompt
(see :mod:`idp.idp.llm.prompts`) so a broken template never takes
the agent down.
"""

from __future__ import annotations

from idp.core.cache import cache_delete, cache_get, cache_set
from idp.core.logger import get_logger

logger = get_logger("idp.llm.prompt_templates")

_CACHE_KEY = "idp:prompt_templates:index"
_TTL_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def find_template(
    *,
    target_doctype: str | None,
    language: str | None,
    template_name: str | None = None,
) -> dict | None:
    """Return the best-matching enabled template row, or ``None``."""

    index = _load_index()
    if not index:
        return None

    if template_name:
        # Caller asked for a specific template by name.
        return next(
            (r for r in index if r["template_name"] == template_name and r["enabled"]),
            None,
        )

    candidates = [r for r in index if r["enabled"]]
    if not candidates:
        return None

    # Prefer the most specific match (target_doctype + language).
    def _score(row: dict) -> int:
        s = 0
        if row.get("target_doctype") and row["target_doctype"] == target_doctype:
            s += 2
        elif row.get("target_doctype"):
            return -1  # mismatch on a specified target — disqualify
        if row.get("language") and row["language"] == language:
            s += 1
        elif row.get("language"):
            return -1  # mismatch on a specified language — disqualify
        return s

    scored = [(r, _score(r)) for r in candidates]
    scored = [t for t in scored if t[1] >= 0]
    if not scored:
        return None
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[0][0]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render(
    template_name: str,
    context: dict,
) -> str | None:
    """Render *template_name* with *context*. Returns ``None`` on failure."""

    row = find_template(
        target_doctype=None,
        language=None,
        template_name=template_name,
    )
    if not row:
        return None
    return _render_row(row, context)


def render_match(
    *,
    target_doctype: str | None,
    language: str | None,
    context: dict,
) -> str | None:
    """Find the best-matching template and render it.

    Returns ``None`` when no template matches or rendering fails — the
    caller is expected to fall back to the legacy hard-coded prompt.
    """

    row = find_template(target_doctype=target_doctype, language=language)
    if not row:
        return None
    return _render_row(row, context)


def _render_row(row: dict, context: dict) -> str | None:
    body = row.get("system_prompt") or ""
    if not body.strip():
        return None
    try:
        from jinja2 import Environment, StrictUndefined

        env = Environment(
            keep_trailing_newline=True,
            autoescape=False,
            undefined=StrictUndefined,
        )
        merged = _apply_defaults(row, context)
        return env.from_string(body).render(**merged)
    except Exception:
        logger.exception(
            "Failed to render prompt template %r — falling back",
            row.get("template_name"),
        )
        return None


def _apply_defaults(row: dict, context: dict) -> dict:
    """Merge declared argument defaults into *context*."""

    merged = dict(context or {})
    for arg in row.get("arguments") or []:
        name = arg.get("arg_name")
        if not name or name in merged:
            continue
        if arg.get("default_value") is not None:
            merged[name] = arg.get("default_value")
    return merged


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_index() -> list[dict]:
    cached = cache_get(_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        import frappe
    except ImportError:
        return []

    try:
        rows = frappe.get_all(
            "IDP Prompt Template",
            fields=[
                "name",
                "template_name",
                "target_doctype",
                "language",
                "enabled",
                "system_prompt",
            ],
            limit_page_length=0,
        )
    except Exception:
        return []

    # Eager-load argument rows for default-value resolution.
    for r in rows:
        try:
            r["enabled"] = int(r.get("enabled") or 0) == 1
            r["arguments"] = frappe.get_all(
                "IDP Prompt Template Argument",
                filters={"parent": r["name"], "parenttype": "IDP Prompt Template"},
                fields=["arg_name", "arg_type", "required", "default_value"],
                limit_page_length=0,
            )
        except Exception:
            r["arguments"] = []

    cache_set(_CACHE_KEY, rows, ttl_seconds=_TTL_SECONDS)
    return rows


def invalidate_template_cache() -> None:
    cache_delete(_CACHE_KEY)


__all__ = [
    "find_template",
    "invalidate_template_cache",
    "render",
    "render_match",
]
