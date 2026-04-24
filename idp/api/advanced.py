# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 15 public API -- templates, batch, feedback, workflow, prompts, fine-tuning.

All endpoints require an authenticated user.  ``frappe.only_for`` gates
the privileged ones (fine-tuning export, prompt seeding) to System
Manager.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.api.advanced")


# ---------------------------------------------------------------------------
# §15.1 Templates
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_templates(target_doctype: str | None = None) -> list[dict]:
	"""Return summary rows for all *IDP Extraction Template* records."""
	from idp.idp.advanced.templates import load_templates

	out: list[dict] = []
	for t in load_templates(target_doctype):
		out.append(
			{
				"name": t.name,
				"target_doctype": t.target_doctype,
				"match_keywords": t.match_keywords,
				"field_mapping_count": len(t.field_mappings),
				"specificity": t.specificity,
			}
		)
	return out


@frappe.whitelist()
def detect_template_for_file(file_url: str, target_doctype: str) -> dict:
	"""Run extraction + template detection on a single file (read-only)."""
	from idp.idp.advanced.templates import detect_template
	from idp.idp.extractors.base import extract_content

	extraction = extract_content(file_url)
	tmpl = detect_template(extraction, target_doctype)
	return {
		"matched": tmpl is not None,
		"template": tmpl.name if tmpl else None,
		"specificity": tmpl.specificity if tmpl else 0,
	}


# ---------------------------------------------------------------------------
# §15.2 Batch
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_batch(
	target_doctype: str,
	file_urls: str | list[str],
	company: str | None = None,
) -> dict:
	"""Create a queued IDP Batch Job."""
	from idp.idp.advanced.batch import create_batch_job

	urls = json.loads(file_urls) if isinstance(file_urls, str) else list(file_urls or [])
	if not urls:
		frappe.throw("file_urls is required and must contain at least one URL")

	job = create_batch_job(
		user=frappe.session.user,
		target_doctype=target_doctype,
		file_urls=urls,
		company=company,
	)
	return {"name": job.name, "status": job.status, "total_files": job.total_files}


@frappe.whitelist()
def create_batch_from_zip_api(target_doctype: str, zip_file_url: str, company: str | None = None) -> dict:
	"""Unpack a ZIP and create a batch job from its contents."""
	from idp.idp.advanced.batch import create_batch_from_zip

	job = create_batch_from_zip(
		user=frappe.session.user,
		target_doctype=target_doctype,
		zip_file_url=zip_file_url,
		company=company,
	)
	return {"name": job.name, "status": job.status, "total_files": job.total_files}


@frappe.whitelist()
def run_batch(job_name: str, create_documents: int | bool = 0) -> dict:
	"""Trigger synchronous processing of a batch job."""
	from idp.idp.advanced.batch import run_batch_job

	_assert_batch_owner(job_name)
	return run_batch_job(job_name, create_documents=bool(int(create_documents)))


@frappe.whitelist()
def enqueue_batch(job_name: str, create_documents: int | bool = 0) -> dict:
	"""Enqueue the batch job on the ``long`` queue."""
	from idp.idp.advanced.batch import enqueue_batch_job

	_assert_batch_owner(job_name)
	enqueue_batch_job(job_name, create_documents=bool(int(create_documents)))
	return {"name": job_name, "queued": True}


@frappe.whitelist()
def get_batch_status(job_name: str) -> dict:
	"""Return status + per-item counters for a batch job."""
	_assert_batch_owner(job_name)
	doc = frappe.get_doc("IDP Batch Job", job_name)
	return {
		"name": doc.name,
		"status": doc.status,
		"total": doc.total_files,
		"processed": doc.processed_files,
		"succeeded": doc.succeeded,
		"failed": doc.failed,
		"needs_review": doc.needs_review,
		"items": [
			{
				"file_url": it.file_url,
				"status": it.status,
				"created_doc": it.created_doc,
				"error": it.error_message,
				"confidence": it.confidence,
			}
			for it in (doc.items or [])
		],
	}


def _assert_batch_owner(job_name: str) -> None:
	user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return
	owner = frappe.db.get_value("IDP Batch Job", job_name, "user")
	if owner != user:
		frappe.throw("Not authorised to access this batch job", frappe.PermissionError)


# ---------------------------------------------------------------------------
# §15.3 Feedback / corrections
# ---------------------------------------------------------------------------


@frappe.whitelist()
def record_correction_api(
	target_doctype: str,
	fieldname: str,
	extracted_value: Any,
	corrected_value: Any,
	source_file_url: str | None = None,
	source_text_snippet: str | None = None,
	supplier_or_customer: str | None = None,
	template_used: str | None = None,
	origin: str = "rule",
) -> dict:
	from idp.idp.advanced.feedback import record_correction

	name = record_correction(
		user=frappe.session.user,
		target_doctype=target_doctype,
		fieldname=fieldname,
		extracted_value=extracted_value,
		corrected_value=corrected_value,
		source_file_url=source_file_url,
		source_text_snippet=source_text_snippet,
		supplier_or_customer=supplier_or_customer,
		template_used=template_used,
		origin=origin,
	)
	return {"name": name}


@frappe.whitelist()
def get_fewshot_prompt(target_doctype: str, supplier_or_customer: str | None = None) -> dict:
	from idp.idp.advanced.feedback import build_fewshot_bundle

	bundle = build_fewshot_bundle(target_doctype, supplier_or_customer=supplier_or_customer)
	return {
		"target_doctype": bundle.target_doctype,
		"examples": [
			{
				"fieldname": ex.fieldname,
				"supplier": ex.supplier_or_customer,
				"prompt_line": ex.as_prompt_line(),
			}
			for ex in bundle.examples
		],
		"rendered": bundle.render(),
	}


@frappe.whitelist()
def weak_spots_report(target_doctype: str, min_occurrences: int = 3) -> list[dict]:
	from idp.idp.advanced.feedback import rule_mapper_weak_spots

	return rule_mapper_weak_spots(target_doctype, min_occurrences=int(min_occurrences))


# ---------------------------------------------------------------------------
# §15.7 Prompt library
# ---------------------------------------------------------------------------


@frappe.whitelist()
def list_prompt_library(industry: str | None = None) -> list[dict]:
	from idp.idp.advanced.prompt_library import list_prompts

	return list_prompts(industry=industry, enabled_only=True)


@frappe.whitelist()
def get_prompt(industry: str, target_doctype: str | None = None) -> dict | None:
	from idp.idp.advanced.prompt_library import load_prompt

	snip = load_prompt(industry, target_doctype)
	return (
		{
			"name": snip.name,
			"industry": snip.industry,
			"target_doctype": snip.target_doctype,
			"body": snip.body,
			"description": snip.description,
		}
		if snip
		else None
	)


@frappe.whitelist()
def reseed_prompt_library(overwrite: int | bool = 0) -> dict:
	"""System Manager only -- reinstall shipped prompts."""
	frappe.only_for("System Manager")
	from idp.idp.advanced.prompt_library import seed_builtin_prompts

	return seed_builtin_prompts(overwrite=bool(int(overwrite)))


# ---------------------------------------------------------------------------
# §15.8 Fine-tuning export
# ---------------------------------------------------------------------------


@frappe.whitelist()
def export_fine_tuning(
	format: str = "openai",
	target_doctype: str | None = None,
	since: str | None = None,
	limit: int | None = None,
) -> dict:
	"""System Manager only -- export a JSONL dataset to site private files."""
	frappe.only_for("System Manager")
	from frappe.utils import get_site_path

	from idp.idp.advanced.fine_tuning import export_dataset

	folder = get_site_path("private", "files", "idp-finetune")
	import os as _os

	_os.makedirs(folder, exist_ok=True)
	path = _os.path.join(folder, f"corrections-{frappe.utils.today()}-{format}.jsonl")

	stats = export_dataset(
		path,
		format=format,
		target_doctype=target_doctype,
		since=since,
		limit=int(limit) if limit else None,
	)
	return {
		"format": stats.format,
		"file_path": stats.file_path,
		"total_rows": stats.total_rows,
		"bytes_written": stats.bytes_written,
	}
