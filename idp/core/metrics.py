# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Observability metrics derived from *IDP Document Log* rows.

The metrics module is a thin, read-only aggregation layer.  It does not
maintain its own state — instead it summarises the audit trail that
``idp.core.audit`` writes into ``IDP Document Log``.

The canonical metric set mirrors the Phase 13 roadmap:

- ``idp_extraction_count``          Total extractions (by doctype / status).
- ``idp_extraction_duration_ms``    Processing time distribution.
- ``idp_ocr_confidence_avg``        Average OCR confidence.
- ``idp_validation_failure_rate``   % of rows finishing in ``Failed``.
- ``idp_record_creation_count``     Rows that reached ``Created``.
- ``idp_comparison_count``          Rows where ``created_document`` is set
  without a new ERPNext doc (a comparison run).

Each public function returns a plain dict so it can be JSON-serialised
straight to a dashboard endpoint or an observability pipeline.
"""

from __future__ import annotations

from statistics import median
from typing import Iterable

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.metrics")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _window_filter(since_hours: int | None) -> dict:
	"""Return a Frappe filter clause for rows created in the last N hours."""
	if since_hours is None or since_hours <= 0:
		return {}
	from frappe.utils import add_to_date, now_datetime

	cutoff = add_to_date(now_datetime(), hours=-since_hours)
	return {"creation": [">=", cutoff]}


def _fetch(fields: list[str], filters: dict) -> list[dict]:
	return frappe.get_all(
		"IDP Document Log",
		filters=filters,
		fields=fields,
		limit=0,  # no cap; dashboards aggregate server-side
	)


def _percentile(values: list[float], pct: float) -> float:
	"""Compute the *pct* percentile of *values* using linear interpolation."""
	if not values:
		return 0.0
	if not 0.0 <= pct <= 100.0:
		raise ValueError("pct must be in [0, 100]")
	ordered = sorted(values)
	if len(ordered) == 1:
		return float(ordered[0])
	k = (len(ordered) - 1) * (pct / 100.0)
	lo = int(k)
	hi = min(lo + 1, len(ordered) - 1)
	frac = k - lo
	return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _duration_stats(values: Iterable[int | float | None]) -> dict:
	"""Return count, mean, median, p95, max for the duration list."""
	clean = [float(v) for v in values if v not in (None, 0)]
	if not clean:
		return {"count": 0, "mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
	return {
		"count": len(clean),
		"mean_ms": round(sum(clean) / len(clean), 2),
		"median_ms": round(float(median(clean)), 2),
		"p95_ms": round(_percentile(clean, 95.0), 2),
		"max_ms": round(max(clean), 2),
	}


# ---------------------------------------------------------------------------
# Public metric functions
# ---------------------------------------------------------------------------


def extraction_count(since_hours: int | None = 24) -> dict:
	"""Count extractions grouped by status and target DocType.

	Args:
		since_hours: Rolling window in hours.  ``None`` = all time.
	"""
	rows = _fetch(["status", "target_doctype"], _window_filter(since_hours))
	by_status: dict[str, int] = {}
	by_doctype: dict[str, int] = {}
	for r in rows:
		by_status[r["status"] or "Unknown"] = by_status.get(r["status"] or "Unknown", 0) + 1
		dt = r["target_doctype"] or "None"
		by_doctype[dt] = by_doctype.get(dt, 0) + 1
	return {
		"window_hours": since_hours,
		"total": len(rows),
		"by_status": by_status,
		"by_doctype": by_doctype,
	}


def extraction_duration(since_hours: int | None = 24) -> dict:
	"""Return processing-time statistics (mean / median / p95 / max)."""
	rows = _fetch(["processing_time_ms"], _window_filter(since_hours))
	stats = _duration_stats(r["processing_time_ms"] for r in rows)
	stats["window_hours"] = since_hours
	return stats


def ocr_confidence(since_hours: int | None = 24) -> dict:
	"""Average OCR confidence across non-null rows in the window."""
	rows = _fetch(["ocr_confidence"], _window_filter(since_hours))
	values = [float(r["ocr_confidence"]) for r in rows if r["ocr_confidence"] is not None]
	if not values:
		return {"window_hours": since_hours, "count": 0, "avg_confidence": 0.0}
	return {
		"window_hours": since_hours,
		"count": len(values),
		"avg_confidence": round(sum(values) / len(values), 4),
		"min_confidence": round(min(values), 4),
		"max_confidence": round(max(values), 4),
	}


def validation_failure_rate(since_hours: int | None = 24) -> dict:
	"""Return % of rows that ended in *Failed* status."""
	rows = _fetch(["status"], _window_filter(since_hours))
	if not rows:
		return {"window_hours": since_hours, "total": 0, "failed": 0, "rate_pct": 0.0}
	failed = sum(1 for r in rows if r["status"] == "Failed")
	total = len(rows)
	return {
		"window_hours": since_hours,
		"total": total,
		"failed": failed,
		"rate_pct": round((failed / total) * 100.0, 2),
	}


def record_creation_count(since_hours: int | None = 24) -> dict:
	"""Count rows that reached *Created* status, broken down by DocType."""
	rows = _fetch(
		["created_doctype"],
		{**_window_filter(since_hours), "status": "Created"},
	)
	by_doctype: dict[str, int] = {}
	for r in rows:
		dt = r["created_doctype"] or "None"
		by_doctype[dt] = by_doctype.get(dt, 0) + 1
	return {
		"window_hours": since_hours,
		"total": len(rows),
		"by_doctype": by_doctype,
	}


def comparison_count(since_hours: int | None = 24) -> dict:
	"""Count comparison runs.

	A comparison is identified as a row that references an existing
	document (``created_document`` present) but whose *status* reached
	``Extracted`` rather than ``Created`` (i.e. the pipeline was
	extract+compare, not extract+create).
	"""
	rows = _fetch(
		["status", "created_document"],
		{
			**_window_filter(since_hours),
			"status": "Extracted",
			"created_document": ["is", "set"],
		},
	)
	return {"window_hours": since_hours, "total": len(rows)}


def dashboard(since_hours: int | None = 24) -> dict:
	"""Bundle every metric into a single payload for a dashboard endpoint."""
	return {
		"extraction_count": extraction_count(since_hours),
		"extraction_duration": extraction_duration(since_hours),
		"ocr_confidence": ocr_confidence(since_hours),
		"validation_failure_rate": validation_failure_rate(since_hours),
		"record_creation_count": record_creation_count(since_hours),
		"comparison_count": comparison_count(since_hours),
	}


# ---------------------------------------------------------------------------
# Whitelisted endpoint
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_dashboard(since_hours: int = 24) -> dict:
	"""HTTP-accessible wrapper around :func:`dashboard`."""
	try:
		window = int(since_hours)
	except (TypeError, ValueError):
		window = 24
	return dashboard(since_hours=window if window > 0 else None)
