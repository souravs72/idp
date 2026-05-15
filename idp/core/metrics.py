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


# ---------------------------------------------------------------------------
# Phase 28 — Token-Efficiency regression check (weekly)
# ---------------------------------------------------------------------------


_TE_FIELDS = (
	"tokens_per_extracted_field",
	"attachment_text_chars_sent",
	"attachment_text_chars_total",
	"vision_calls_in_request",
	"cached_tokens",
	"model_tier",
)
_DEFAULT_TE_REGRESSION_PCT = 15


def _avg_tokens_per_field(rows: list[dict]) -> float | None:
	"""Return the mean ``tokens_per_extracted_field`` across *rows*.

	None when the metric is missing on every row (older installs, or a
	week without any LLM-touched extractions).
	"""

	values: list[float] = []
	for r in rows:
		val = r.get("tokens_per_extracted_field")
		if val is None or val == "":
			continue
		try:
			values.append(float(val))
		except (TypeError, ValueError):
			continue
	if not values:
		return None
	return sum(values) / len(values)


def weekly_te_summary() -> dict:
	"""Compute this-week vs. previous-week TE metrics from IDP Document Log."""

	this_week = _fetch(
		list(_TE_FIELDS) + ["creation"],
		_window_filter(24 * 7),
	)
	from frappe.utils import add_to_date, now_datetime

	prev_lower = add_to_date(now_datetime(), hours=-24 * 14)
	prev_upper = add_to_date(now_datetime(), hours=-24 * 7)
	prev_week = frappe.get_all(
		"IDP Document Log",
		filters={"creation": ["between", [prev_lower, prev_upper]]},
		fields=list(_TE_FIELDS) + ["creation"],
		limit=0,
	)

	cur_avg = _avg_tokens_per_field(this_week)
	prev_avg = _avg_tokens_per_field(prev_week)
	delta_pct: float | None = None
	if cur_avg is not None and prev_avg and prev_avg > 0:
		delta_pct = (cur_avg - prev_avg) / prev_avg * 100.0
	return {
		"this_week": {
			"rows": len(this_week),
			"avg_tokens_per_field": cur_avg,
		},
		"previous_week": {
			"rows": len(prev_week),
			"avg_tokens_per_field": prev_avg,
		},
		"delta_pct": delta_pct,
	}


def weekly_te_regression_check() -> dict:
	"""Phase 28 — emit an Email Alert when TE regresses week-over-week.

	Wired into ``hooks.scheduler_events.weekly``.  Compares the average
	``tokens_per_extracted_field`` over the last 7 days to the prior
	7-day window; when the increase exceeds
	``IDP Settings.te_regression_alert_pct`` (default 15) an Email Alert
	is enqueued for System Managers.

	The job is best-effort: any failure is logged and swallowed so a
	misconfigured SMTP setup never breaks the scheduler.
	"""

	try:
		summary = weekly_te_summary()
	except Exception:
		logger.exception("weekly TE summary failed")
		return {"status": "error", "stage": "summary"}

	delta_pct = summary.get("delta_pct")
	if delta_pct is None:
		return {"status": "skipped", "reason": "insufficient_data", **summary}

	try:
		threshold = int(
			frappe.db.get_single_value("IDP Settings", "te_regression_alert_pct")
			or _DEFAULT_TE_REGRESSION_PCT
		)
	except Exception:
		threshold = _DEFAULT_TE_REGRESSION_PCT

	if delta_pct <= threshold:
		return {"status": "ok", "threshold_pct": threshold, **summary}

	# Regression detected — emit a System-Manager-targeted email alert.
	try:
		recipients = _system_manager_emails()
		if recipients:
			cur = summary["this_week"]["avg_tokens_per_field"]
			prev = summary["previous_week"]["avg_tokens_per_field"]
			subject = (
				f"IDP token-efficiency regression: +{delta_pct:.1f}% "
				f"(threshold {threshold}%)"
			)
			message = (
				"<p>Weekly IDP token-efficiency check has detected a "
				"regression in <b>tokens_per_extracted_field</b>.</p>"
				f"<ul>"
				f"<li>This week: <b>{cur:.2f}</b> (rows: {summary['this_week']['rows']})</li>"
				f"<li>Previous week: <b>{prev:.2f}</b> (rows: {summary['previous_week']['rows']})</li>"
				f"<li>Change: <b>+{delta_pct:.1f}%</b> (alert threshold: {threshold}%)</li>"
				"</ul>"
				"<p>Investigate recent changes to extraction templates, "
				"mapper version, or LLM routes.  See <i>IDP Document Log</i> "
				"for per-document detail.</p>"
			)
			frappe.sendmail(
				recipients=recipients,
				subject=subject,
				message=message,
				delayed=False,
				retry=1,
			)
	except Exception:
		logger.exception("weekly TE regression alert email failed")
		return {"status": "alerted_but_email_failed", "threshold_pct": threshold, **summary}

	return {"status": "alerted", "threshold_pct": threshold, **summary}


def _system_manager_emails() -> list[str]:
	"""Return the email addresses of users with the System Manager role."""

	try:
		users = frappe.get_all(
			"Has Role",
			filters={"role": "System Manager", "parenttype": "User"},
			fields=["parent"],
			limit=0,
		)
	except Exception:
		return []
	emails: list[str] = []
	for row in users:
		parent = row.get("parent")
		if not parent or parent in {"Administrator", "Guest"}:
			continue
		try:
			user_doc = frappe.db.get_value(
				"User", parent, ["email", "enabled"], as_dict=True
			)
		except Exception:
			continue
		if user_doc and user_doc.get("enabled") and user_doc.get("email"):
			emails.append(user_doc["email"])
	return emails
