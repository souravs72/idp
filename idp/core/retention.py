# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Scheduled retention and cleanup for IDP Document Log (Phase 14).

Old audit rows accumulate quickly on busy sites.  The helpers below
archive / delete rows older than a configurable threshold and wipe
any temporary files that the extraction pipeline may have left behind
on disk.

Configuration (IDP Settings, with roadmap defaults when absent):

* ``log_retention_days``     — rows older than this are *archived*
  (status flipped to ``Failed`` if still ``Uploaded``/``Extracting``,
  otherwise left alone) and eligible for pruning. Default: 90.
* ``log_prune_after_days``   — rows older than this are physically
  deleted. Default: 365.
* ``temp_dir``               — directory that the OCR preprocessor
  may drop temporary images into. Default: site's ``temp`` folder.

All helpers are **idempotent** and **safe to run on an empty DB**;
they return diagnostic dicts that the daily scheduler job can log.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.retention")


DEFAULT_LOG_RETENTION_DAYS = 90
DEFAULT_LOG_PRUNE_DAYS = 365
DEFAULT_TEMP_MAX_AGE_HOURS = 24


# ---------------------------------------------------------------------------
# Settings lookup
# ---------------------------------------------------------------------------


def _get_retention_config() -> dict:
	"""Return retention knobs, honouring IDP Settings overrides."""
	try:
		settings = frappe.get_cached_doc("IDP Settings")
	except Exception:
		settings = None

	def _field(name: str, default: int) -> int:
		val = getattr(settings, name, None) if settings else None
		try:
			return int(val) if val else default
		except (TypeError, ValueError):
			return default

	return {
		"log_retention_days": _field("log_retention_days", DEFAULT_LOG_RETENTION_DAYS),
		"log_prune_after_days": _field("log_prune_after_days", DEFAULT_LOG_PRUNE_DAYS),
		"temp_max_age_hours": _field("temp_max_age_hours", DEFAULT_TEMP_MAX_AGE_HOURS),
	}


# ---------------------------------------------------------------------------
# Log archival + pruning
# ---------------------------------------------------------------------------


def archive_stale_logs(older_than_days: int | None = None) -> dict:
	"""Mark orphaned ``Uploaded``/``Extracting`` rows as ``Failed``.

	Rows that have been in a transient state longer than
	*older_than_days* almost certainly belong to a crashed worker.
	We transition them to ``Failed`` so metrics don't double-count
	them as "in-flight".
	"""
	cfg = _get_retention_config()
	threshold = older_than_days if older_than_days is not None else cfg["log_retention_days"]
	if threshold <= 0:
		return {"archived": 0, "threshold_days": threshold}

	try:
		from frappe.utils import add_to_date, now_datetime
	except Exception:  # pragma: no cover — pure-mode fallback
		return {"archived": 0, "threshold_days": threshold}

	cutoff = add_to_date(now_datetime(), days=-threshold)
	try:
		affected = frappe.db.sql(
			"""
			UPDATE `tabIDP Document Log`
			SET status = 'Failed',
				error_message = COALESCE(error_message, 'Auto-archived: stale in-flight row.')
			WHERE status IN ('Uploaded', 'Extracting', 'Creating')
			  AND modified < %(cutoff)s
			""",
			{"cutoff": cutoff},
		)
		frappe.db.commit()
		count = frappe.db.sql(
			"""
			SELECT COUNT(*) FROM `tabIDP Document Log`
			WHERE status = 'Failed' AND modified >= %(recent)s
			""",
			{"recent": cutoff},
			as_list=True,
		)
		archived = int(count[0][0]) if count and count[0] else 0
	except Exception:
		logger.warning("archive_stale_logs: SQL path failed", exc_info=True)
		archived = 0

	return {"archived": archived, "threshold_days": threshold, "cutoff": str(cutoff)}


def prune_old_logs(older_than_days: int | None = None) -> dict:
	"""Delete log rows older than *older_than_days*.

	Returns a dict with ``deleted`` count and the cutoff used.
	Caller is expected to invoke this from a scheduled job so the
	cost is amortised away from the request hot path.
	"""
	cfg = _get_retention_config()
	threshold = older_than_days if older_than_days is not None else cfg["log_prune_after_days"]
	if threshold <= 0:
		return {"deleted": 0, "threshold_days": threshold}

	try:
		from frappe.utils import add_to_date, now_datetime
	except Exception:  # pragma: no cover
		return {"deleted": 0, "threshold_days": threshold}

	cutoff = add_to_date(now_datetime(), days=-threshold)
	try:
		rows = frappe.get_all(
			"IDP Document Log",
			filters={"creation": ["<", cutoff]},
			fields=["name"],
			limit=0,
		)
		for row in rows:
			frappe.delete_doc("IDP Document Log", row["name"], ignore_permissions=True, force=1)
		frappe.db.commit()
		deleted = len(rows)
	except Exception:
		logger.warning("prune_old_logs failed", exc_info=True)
		deleted = 0

	return {"deleted": deleted, "threshold_days": threshold, "cutoff": str(cutoff)}


# ---------------------------------------------------------------------------
# Temporary file cleanup
# ---------------------------------------------------------------------------


def _default_temp_dir() -> Path | None:
	try:
		return Path(frappe.get_site_path()) / "temp"
	except Exception:
		return None


def purge_temp_files(max_age_hours: int | None = None, directory: str | None = None) -> dict:
	"""Delete files in *directory* older than *max_age_hours*.

	Files younger than the cutoff are preserved.  Directory traversal
	is shallow by design — we never recurse beyond the immediate
	children to keep the job bounded.
	"""
	cfg = _get_retention_config()
	max_age = max_age_hours if max_age_hours is not None else cfg["temp_max_age_hours"]
	if max_age <= 0:
		return {"deleted": 0, "directory": directory, "max_age_hours": max_age}

	path = Path(directory) if directory else _default_temp_dir()
	if path is None or not path.exists():
		return {"deleted": 0, "directory": str(path), "max_age_hours": max_age}

	cutoff = time.time() - (max_age * 3600)
	deleted = 0
	for entry in path.iterdir():
		if not entry.is_file():
			continue
		try:
			if entry.stat().st_mtime < cutoff:
				entry.unlink()
				deleted += 1
		except OSError:
			logger.warning("Could not delete temp file %s", entry, exc_info=True)

	return {"deleted": deleted, "directory": str(path), "max_age_hours": max_age}


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def daily() -> dict:
	"""Daily scheduled task invoked by Frappe's scheduler.

	Wired in ``hooks.py`` via ``scheduler_events["daily"]``.  Returns
	a summary dict so the scheduler log captures the outcome.
	"""
	logger.info("IDP retention: daily run started")
	report = {
		"archived": archive_stale_logs(),
		"pruned": prune_old_logs(),
		"temp_files": purge_temp_files(),
	}
	logger.info("IDP retention: daily run finished: %s", report)
	return report
