# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 29 — Confidence band helper.

Converts numeric confidence scores into a three-state visual language
(``green`` / ``amber`` / ``red``) for the ConfirmationCard UI.

Thresholds are sourced (in order of precedence):
    1. Per-DocType overrides on ``IDP Extraction Template``
       (``confidence_amber_threshold`` / ``confidence_red_threshold``).
    2. ``IDP Settings`` global defaults.
    3. Hard-coded fallbacks (0.75 / 0.55).

Designed to be cheap and safe to call from request paths: a single
``frappe.get_cached_doc`` per DocType, fully isolated from Frappe in tests
(it falls back to defaults when Frappe is not initialised).
"""

from __future__ import annotations

from typing import Literal

try:
    import frappe
except Exception:  # pragma: no cover — unit tests without Frappe bootstrap
    frappe = None  # type: ignore[assignment]


Band = Literal["green", "amber", "red"]

# Hard-coded fallbacks; mirror the field defaults declared on
# ``IDP Extraction Template`` so the UI degrades gracefully when a
# template / settings row is missing.
_DEFAULT_AMBER = 0.75
_DEFAULT_RED = 0.55


def _safe_float(value: object, fallback: float) -> float:
    try:
        if value is None or value == "":
            return fallback
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _resolve_thresholds(doctype: str | None) -> tuple[float, float]:
    """Return ``(amber, red)`` thresholds for the given target DocType.

    Never raises — falls back to module defaults on any error so the UI
    never blocks on a confidence-band lookup.
    """
    amber = _DEFAULT_AMBER
    red = _DEFAULT_RED

    if frappe is None:
        return amber, red

    # Per-doctype override on IDP Extraction Template
    if doctype:
        try:
            template_name = frappe.db.get_value(
                "IDP Extraction Template",
                {"target_doctype": doctype},
                "name",
            )
            if template_name:
                tpl = frappe.get_cached_doc("IDP Extraction Template", template_name)
                amber = _safe_float(getattr(tpl, "confidence_amber_threshold", None), amber)
                red = _safe_float(getattr(tpl, "confidence_red_threshold", None), red)
        except Exception:
            pass

    # Ensure ordering invariant: amber > red. If misconfigured, swap.
    if red > amber:
        amber, red = red, amber
    return amber, red


def band_for(value: float | None, doctype: str | None = None) -> Band:
    """Classify ``value`` into a confidence band for ``doctype``.

    ``None`` and unparseable values are treated as the lowest band
    (``"red"``) so they surface for review rather than silently passing
    as confident.
    """
    if value is None:
        return "red"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "red"

    amber, red = _resolve_thresholds(doctype)
    if v >= amber:
        return "green"
    if v >= red:
        return "amber"
    return "red"


def is_enabled() -> bool:
    """Return whether the confidence-dot UI is enabled in Settings.

    Defaults to ``True`` (Phase 29 default behaviour).
    """
    if frappe is None:
        return True
    try:
        settings = frappe.get_cached_doc("IDP Settings")
        val = getattr(settings, "show_confidence_dots", 1)
        return bool(int(val)) if val is not None else True
    except Exception:
        return True
