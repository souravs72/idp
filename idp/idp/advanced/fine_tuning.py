# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.8 — Fine-tuning dataset exporter.

Export accumulated :class:`IDP Extraction Correction` records as
training pairs in one of the common fine-tuning formats.

Supported output formats
------------------------

``openai``
    JSONL with chat-completions-style messages:
    ``{"messages": [{"role": "system", ...}, {"role": "user", ...},
    {"role": "assistant", ...}]}``.
``anthropic``
    JSONL with Claude-style message pairs.
``plain``
    JSONL with flat ``{"input": ..., "output": ...}``.

The exporter never ships raw documents -- only the text snippet that
the user originally corrected is included, minimising PII leakage.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.advanced.fine_tuning")


@dataclass
class ExportStats:
	format: str
	file_path: str
	total_rows: int
	bytes_written: int


# ---------------------------------------------------------------------------
# Row iteration
# ---------------------------------------------------------------------------


def iter_corrections(
	*,
	target_doctype: str | None = None,
	since: str | date | datetime | None = None,
	limit: int | None = None,
) -> list[dict]:
	"""Pull corrections matching *target_doctype* / *since* cut-offs."""
	filters: dict[str, Any] = {}
	if target_doctype:
		filters["target_doctype"] = target_doctype
	if since:
		filters["creation"] = [">=", str(since)]

	rows = frappe.get_all(
		"IDP Extraction Correction",
		filters=filters,
		fields=[
			"name",
			"target_doctype",
			"fieldname",
			"extracted_value",
			"corrected_value",
			"source_text_snippet",
			"supplier_or_customer",
			"origin",
			"creation",
		],
		order_by="creation asc",
		limit=limit or 0,
	)
	return rows


# ---------------------------------------------------------------------------
# Row renderers
# ---------------------------------------------------------------------------


def _system_prompt(target_doctype: str) -> str:
	return (
		f"You are a careful field-extraction assistant for ERPNext. "
		f"Given a snippet from a {target_doctype} document, return the value "
		f"for the requested fieldname. Respond with the value only, no commentary."
	)


def _to_openai(row: dict) -> dict:
	return {
		"messages": [
			{"role": "system", "content": _system_prompt(row["target_doctype"])},
			{
				"role": "user",
				"content": (
					f"Fieldname: {row['fieldname']}\nSnippet:\n{row.get('source_text_snippet') or ''}"
				),
			},
			{"role": "assistant", "content": row["corrected_value"] or ""},
		]
	}


def _to_anthropic(row: dict) -> dict:
	return {
		"system": _system_prompt(row["target_doctype"]),
		"messages": [
			{
				"role": "user",
				"content": (
					f"Fieldname: {row['fieldname']}\nSnippet:\n{row.get('source_text_snippet') or ''}"
				),
			},
			{"role": "assistant", "content": row["corrected_value"] or ""},
		],
	}


def _to_plain(row: dict) -> dict:
	return {
		"input": {
			"doctype": row["target_doctype"],
			"fieldname": row["fieldname"],
			"snippet": row.get("source_text_snippet") or "",
		},
		"output": row["corrected_value"] or "",
	}


_FORMATTERS = {
	"openai": _to_openai,
	"anthropic": _to_anthropic,
	"plain": _to_plain,
}


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def export_dataset(
	output_path: str,
	*,
	format: str = "openai",
	target_doctype: str | None = None,
	since: str | None = None,
	limit: int | None = None,
	min_snippet_len: int = 20,
) -> ExportStats:
	"""Write a JSONL fine-tuning dataset to *output_path*.

	Rows without a sufficiently long ``source_text_snippet`` are dropped
	(controlled by *min_snippet_len*) because they offer no useful
	context for a learner.
	"""
	if format not in _FORMATTERS:
		raise ValueError(f"Unknown format: {format!r}. Must be one of {list(_FORMATTERS)}")

	rows = iter_corrections(target_doctype=target_doctype, since=since, limit=limit)
	formatter = _FORMATTERS[format]
	os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

	written = 0
	total_bytes = 0
	with open(output_path, "w", encoding="utf-8") as fh:
		for row in rows:
			snippet = row.get("source_text_snippet") or ""
			if len(snippet) < min_snippet_len:
				continue
			line = json.dumps(formatter(row), ensure_ascii=False)
			fh.write(line + "\n")
			written += 1
			total_bytes += len(line) + 1

	stats = ExportStats(format=format, file_path=output_path, total_rows=written, bytes_written=total_bytes)
	logger.info(f"Fine-tuning export: format={format} -> {output_path} ({written} rows, {total_bytes} bytes)")
	return stats


# ---------------------------------------------------------------------------
# Scheduled export (weekly)
# ---------------------------------------------------------------------------


def weekly_export() -> dict:
	"""Scheduler hook: snapshot last-30-day corrections into site private files.

	Produces three files (openai / anthropic / plain) under
	``sites/<site>/private/files/idp-finetune/``.  Returns a summary dict.
	"""
	try:
		from frappe.utils import get_site_path
	except Exception:
		return {"skipped": "not running inside a Frappe site"}

	folder = os.path.join(get_site_path("private", "files"), "idp-finetune")
	os.makedirs(folder, exist_ok=True)

	stamp = datetime.now().strftime("%Y%m%d")
	since = frappe.utils.add_days(frappe.utils.today(), -30)

	summary: dict[str, Any] = {"folder": folder, "files": []}
	for fmt in _FORMATTERS:
		path = os.path.join(folder, f"corrections-{stamp}-{fmt}.jsonl")
		stats = export_dataset(path, format=fmt, since=since)
		summary["files"].append({"format": stats.format, "path": stats.file_path, "rows": stats.total_rows})
	return summary
