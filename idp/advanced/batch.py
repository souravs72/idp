# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.2 — Batch processing.

Accept a list of file URLs (or a single ZIP file) and run the extraction
pipeline on each in a background worker, tracking progress in an
*IDP Batch Job* document.

Usage
-----

.. code-block:: python

    from idp.advanced.batch import create_batch_job, run_batch_job

    job = create_batch_job(
        user="user@example.com",
        target_doctype="Purchase Invoice",
        file_urls=["/files/a.pdf", "/files/b.pdf"],
        company="Demo Co",
    )
    run_batch_job(job.name)  # synchronous; use enqueue_batch_job() for async
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import zipfile
from dataclasses import dataclass

import frappe
from frappe.utils import now_datetime

from idp.core.exceptions import ExtractionError, IDPError
from idp.core.logger import get_logger
from idp.extractors.base import extract_content
from idp.mappers.document_creator import create_document
from idp.mappers.mapper import FieldMapper

logger = get_logger("idp.advanced.batch")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class BatchItemResult:
	file_url: str
	status: str  # Success | Failed | Needs Review
	created_doc: str | None = None
	error_message: str | None = None
	confidence: float | None = None
	duration_ms: int = 0
	warnings: list[str] | None = None


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------


def create_batch_job(
	user: str,
	target_doctype: str,
	file_urls: list[str],
	*,
	company: str | None = None,
) -> "frappe.model.document.Document":
	"""Create a queued ``IDP Batch Job`` with one child row per file URL."""
	if not file_urls:
		raise IDPError("create_batch_job requires at least one file_url")

	job = frappe.new_doc("IDP Batch Job")
	job.user = user
	job.target_doctype = target_doctype
	job.company = company
	job.status = "Queued"

	for url in file_urls:
		job.append(
			"items",
			{
				"file_url": url,
				"file_name": os.path.basename(url),
				"status": "Pending",
			},
		)

	job.insert(ignore_permissions=False)
	logger.info(f"Batch job {job.name} created with {len(file_urls)} files")
	return job


def create_batch_from_zip(
	user: str,
	target_doctype: str,
	zip_file_url: str,
	*,
	company: str | None = None,
) -> "frappe.model.document.Document":
	"""Unpack *zip_file_url* into Frappe's file store and queue each entry.

	Every non-directory entry in the archive becomes a private file on the
	site and is appended to the new batch job.
	"""
	from frappe.utils.file_manager import save_file

	# Resolve the ZIP path via our secure resolver
	from idp.extractors.base import resolve_file

	zip_path, mime = resolve_file(zip_file_url)
	if not zip_path.lower().endswith(".zip") and "zip" not in (mime or ""):
		raise IDPError(f"File does not look like a ZIP archive: {zip_file_url}")

	file_urls: list[str] = []
	with zipfile.ZipFile(zip_path, "r") as zf:
		for info in zf.infolist():
			if info.is_dir():
				continue
			# Skip hidden/system entries
			base = os.path.basename(info.filename)
			if not base or base.startswith("."):
				continue
			with zf.open(info) as src, tempfile.NamedTemporaryFile(delete=False) as dst:
				dst.write(src.read())
				dst_path = dst.name
			try:
				with open(dst_path, "rb") as fh:
					file_doc = save_file(
						base,
						fh.read(),
						"",
						"",
						is_private=1,
					)
				file_urls.append(file_doc.file_url)
			finally:
				if os.path.exists(dst_path):
					os.unlink(dst_path)

	if not file_urls:
		raise IDPError(f"No usable files found in ZIP {zip_file_url}")

	return create_batch_job(user, target_doctype, file_urls, company=company)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_batch_job(
	job_name: str,
	*,
	create_documents: bool = False,
	use_templates: bool = True,
) -> dict:
	"""Process every pending item in *job_name*.

	Parameters
	----------
	create_documents:
	    When ``False`` (default) the pipeline stops after extraction +
	    mapping and marks items as **Needs Review**, letting the user
	    inspect before documents are written.  Pass ``True`` to create
	    ERPNext records automatically.
	use_templates:
	    If ``True`` (default) each file is checked against the
	    *IDP Extraction Template* catalogue; when no template matches
	    the file is mapped with the plain :class:`FieldMapper`.  Templates
	    are **always optional** -- a job succeeds whether or not one fires.
	"""
	job = frappe.get_doc("IDP Batch Job", job_name)
	if job.status in ("Completed", "Cancelled"):
		return _summary(job)

	job.status = "Running"
	job.started_on = job.started_on or now_datetime()
	job.save(ignore_permissions=True)

	mapper = FieldMapper()

	for row in job.get("items") or []:
		if row.status in ("Success", "Failed"):
			continue
		result = _process_one(
			row.file_url, job.target_doctype, mapper, job.company, create_documents, use_templates
		)
		row.status = result.status
		row.created_doc = result.created_doc
		row.error_message = result.error_message
		row.confidence = result.confidence
		row.duration_ms = result.duration_ms
		row.warnings = json.dumps(result.warnings or [])
		job.save(ignore_permissions=True)  # incremental save keeps progress visible

	# Final save writes the computed summary
	job.reload()
	job.summary_report = json.dumps(_summary(job), default=str)
	job.save(ignore_permissions=True)
	logger.info(
		f"Batch job {job.name} finished: {job.succeeded} ok / {job.failed} fail / {job.needs_review} review"
	)
	return _summary(job)


def _process_one(
	file_url: str,
	target_doctype: str,
	mapper: FieldMapper,
	company: str | None,
	create_documents: bool,
	use_templates: bool = True,
) -> BatchItemResult:
	t0 = time.monotonic()
	warnings: list[str] = []
	try:
		extraction = extract_content(file_url)

		# Templates are optional: try to auto-detect one; fall back to plain mapper.
		mapped = None
		if use_templates:
			try:
				from idp.advanced.templates import match_and_apply

				mapped, _template = match_and_apply(extraction, target_doctype, company=company)
			except Exception as exc:  # never let template logic break the pipeline
				logger.warning(f"Template lookup failed for {file_url}: {exc}")

		if mapped is None:
			mapped = mapper.map_fields(extraction, target_doctype, company=company)

		warnings = list(mapped.warnings)
		confidence = _avg_confidence(mapped.confidence_scores)

		if create_documents:
			try:
				created = create_document(mapped, company=company or "")
				return BatchItemResult(
					file_url=file_url,
					status="Success",
					created_doc=created.get("name"),
					confidence=confidence,
					duration_ms=int((time.monotonic() - t0) * 1000),
					warnings=warnings,
				)
			except Exception as exc:
				return BatchItemResult(
					file_url=file_url,
					status="Needs Review",
					error_message=f"Mapping OK but creation failed: {exc}",
					confidence=confidence,
					duration_ms=int((time.monotonic() - t0) * 1000),
					warnings=warnings,
				)

		return BatchItemResult(
			file_url=file_url,
			status="Needs Review",
			confidence=confidence,
			duration_ms=int((time.monotonic() - t0) * 1000),
			warnings=warnings,
		)
	except ExtractionError as exc:
		return BatchItemResult(
			file_url=file_url,
			status="Failed",
			error_message=str(exc),
			duration_ms=int((time.monotonic() - t0) * 1000),
		)
	except Exception as exc:  # catch-all -- never let one file kill the job
		logger.exception(f"Unexpected error processing {file_url}")
		return BatchItemResult(
			file_url=file_url,
			status="Failed",
			error_message=f"{type(exc).__name__}: {exc}",
			duration_ms=int((time.monotonic() - t0) * 1000),
		)


def _avg_confidence(scores: dict) -> float | None:
	if not scores:
		return None
	vals = [float(v) for v in scores.values() if isinstance(v, (int, float))]
	return round(sum(vals) / len(vals), 3) if vals else None


def _summary(job: "frappe.model.document.Document") -> dict:
	return {
		"job": job.name,
		"status": job.status,
		"total": job.total_files,
		"succeeded": job.succeeded,
		"failed": job.failed,
		"needs_review": job.needs_review,
		"started_on": job.started_on,
		"completed_on": job.completed_on,
	}


# ---------------------------------------------------------------------------
# Background dispatch
# ---------------------------------------------------------------------------


def enqueue_batch_job(job_name: str, *, create_documents: bool = False, use_templates: bool = True) -> str:
	"""Enqueue :func:`run_batch_job` on the ``long`` queue."""
	from frappe.utils.background_jobs import enqueue

	enqueue(
		"idp.advanced.batch.run_batch_job",
		queue="long",
		timeout=3600,
		job_name=job_name,
		create_documents=create_documents,
		use_templates=use_templates,
		enqueue_after_commit=True,
	)
	return job_name
