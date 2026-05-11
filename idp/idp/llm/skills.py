# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Reusable extraction skills (Phase 26 §26.6).

Skills are short, focused markdown blocks (extraction rules,
worked examples) that the admin attaches to a target DocType +
language pair.  :func:`get_skills_block` returns the concatenated
markdown for the conversation's context — it is appended to the
system prompt after the template body and before the tool
descriptions.

Skills are intentionally separate from prompt templates so a single
template can reuse rules shared across multiple DocTypes (e.g. a
"VAT compliance" skill referenced by both Sales Invoice and
Purchase Invoice templates).
"""

from __future__ import annotations

from idp.core.cache import cache_delete, cache_get, cache_set
from idp.core.logger import get_logger

logger = get_logger("idp.llm.skills")

_CACHE_KEY = "idp:skills:index"
_TTL_SECONDS = 300.0


def get_skills_block(
    *,
    target_doctype: str | None,
    language: str | None,
) -> str:
    """Return the concatenated markdown for skills matching *target_doctype*
    and/or *language*.  Returns an empty string when none match.
    """

    index = _load_index()
    if not index:
        return ""

    matched: list[dict] = []
    for row in index:
        if not row.get("enabled"):
            continue
        rd = row.get("target_doctype")
        rl = row.get("language")
        if rd and rd != target_doctype:
            continue
        if rl and rl != language:
            continue
        matched.append(row)

    if not matched:
        return ""

    parts: list[str] = ["### Extraction Skills"]
    for row in matched:
        title = row.get("skill_name") or "Skill"
        body = (row.get("markdown_content") or "").strip()
        if not body:
            continue
        parts.append(f"\n**{title}**\n\n{body}")
    return "\n".join(parts).strip()


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
            "IDP Skill",
            fields=[
                "name",
                "skill_name",
                "target_doctype",
                "language",
                "enabled",
                "markdown_content",
            ],
            limit_page_length=0,
        )
    except Exception:
        return []

    for r in rows:
        r["enabled"] = int(r.get("enabled") or 0) == 1

    cache_set(_CACHE_KEY, rows, ttl_seconds=_TTL_SECONDS)
    return rows


def invalidate_skills_cache() -> None:
    cache_delete(_CACHE_KEY)


__all__ = ["get_skills_block", "invalidate_skills_cache"]
