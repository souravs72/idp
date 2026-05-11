# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.1 — Extraction templates.

User-defined templates for recurring document formats. A template stores:

* ``field_mappings``    — JSON: custom keyword → fieldname overrides.
* ``validation_rules``  — JSON: required-field + range overrides.
* ``match_keywords``    — list of substrings that auto-select this template
  when they all appear in the extracted text (e.g. supplier name + GSTIN).

The matcher picks the **most specific** template (longest joint keyword
match) that applies to the current document + target DocType.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import frappe

from idp.core.logger import get_logger
from idp.extractors.base import ExtractionResult
from idp.mappers.base import MappedDocument
from idp.mappers.mapper import FieldMapper

logger = get_logger("idp.advanced.templates")


# ---------------------------------------------------------------------------
# Template data model
# ---------------------------------------------------------------------------


@dataclass
class LoadedTemplate:
	"""Hydrated view of an IDP Extraction Template row."""

	name: str
	target_doctype: str
	field_mappings: dict[str, str] = field(default_factory=dict)
	validation_rules: dict[str, Any] = field(default_factory=dict)
	match_keywords: list[str] = field(default_factory=list)

	@property
	def specificity(self) -> int:
		"""Rough score for tie-breaking during matching."""
		return len(self.match_keywords) * 10 + len(self.field_mappings)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_templates(target_doctype: str | None = None) -> list[LoadedTemplate]:
	"""Return all templates as ``LoadedTemplate`` objects.

	Filters by *target_doctype* when provided.
	"""
	filters: dict[str, Any] = {}
	if target_doctype:
		filters["target_doctype"] = target_doctype

	rows = frappe.get_all(
		"IDP Extraction Template",
		filters=filters,
		fields=["name", "target_doctype", "field_mappings", "validation_rules"],
	)
	loaded: list[LoadedTemplate] = []
	for row in rows:
		loaded.append(_hydrate(row))
	return loaded


def _hydrate(row: dict) -> LoadedTemplate:
	"""Parse JSON fields and split match keywords out of ``field_mappings``.

	``field_mappings`` JSON shape (either):

	1. Flat ``{keyword: fieldname}`` dict (legacy) -> stored as-is.
	2. Structured ``{"mappings": {...}, "match_keywords": [...]}``
	   which separates matching hints from mapping overrides.
	"""
	raw_maps = row.get("field_mappings") or "{}"
	raw_rules = row.get("validation_rules") or "{}"

	mappings_obj = _safe_load(raw_maps)
	rules_obj = _safe_load(raw_rules)

	if isinstance(mappings_obj, dict) and "mappings" in mappings_obj:
		mappings = mappings_obj.get("mappings") or {}
		match_keywords = mappings_obj.get("match_keywords") or []
	else:
		mappings = mappings_obj if isinstance(mappings_obj, dict) else {}
		match_keywords = []

	return LoadedTemplate(
		name=row["name"],
		target_doctype=row["target_doctype"],
		field_mappings={str(k).lower(): str(v) for k, v in mappings.items()},
		validation_rules=rules_obj if isinstance(rules_obj, dict) else {},
		match_keywords=[str(k) for k in match_keywords if str(k).strip()],
	)


def _safe_load(value: Any) -> Any:
	if isinstance(value, (dict, list)):
		return value
	if not value:
		return {}
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return {}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def detect_template(
	extracted: ExtractionResult,
	target_doctype: str,
) -> LoadedTemplate | None:
	"""Select the best-fit template for *extracted* against *target_doctype*.

	Matching rule: every keyword in ``match_keywords`` (case-insensitive)
	must appear somewhere in ``extracted.text``.  Among templates that
	match, the one with the highest :pyattr:`LoadedTemplate.specificity`
	wins.  Returns ``None`` when nothing matches.
	"""
	text = (extracted.text or "").lower()
	if not text:
		return None

	candidates = [t for t in load_templates(target_doctype) if t.match_keywords]
	best: LoadedTemplate | None = None
	best_score = -1

	for t in candidates:
		if all(_kw_in_text(kw, text) for kw in t.match_keywords):
			if t.specificity > best_score:
				best = t
				best_score = t.specificity

	if best:
		logger.info(
			f"Template matched: {best.name} (doctype={target_doctype}, "
			f"keywords={best.match_keywords}, specificity={best.specificity})"
		)
	return best


def _kw_in_text(keyword: str, text_lower: str) -> bool:
	keyword = keyword.strip().lower()
	if not keyword:
		return False
	# Word-boundary where possible, fallback to substring for phrases
	if re.fullmatch(r"\w+", keyword):
		return re.search(rf"\b{re.escape(keyword)}\b", text_lower) is not None
	return keyword in text_lower


# ---------------------------------------------------------------------------
# Applying a template
# ---------------------------------------------------------------------------


def apply_template(
	template: LoadedTemplate,
	extracted: ExtractionResult,
	mapped: MappedDocument | None = None,
	*,
	company: str | None = None,
) -> MappedDocument:
	"""Run :class:`FieldMapper` with the template's overrides applied.

	If *mapped* is ``None`` a fresh mapping is produced; otherwise the
	template's ``field_mappings`` are merged into the existing header
	(template values never overwrite high-confidence fields).
	"""
	mapper = _mapper_with_overrides(template)

	if mapped is None:
		mapped = mapper.map_fields(extracted, template.target_doctype, company=company)
	else:
		# Merge template keyword hits into the existing mapping
		_merge_template_hits(mapper, extracted, template, mapped)

	# Persist provenance so downstream consumers know a template fired
	mapped.warnings.append(f"Template applied: {template.name}")
	return mapped


def _mapper_with_overrides(template: LoadedTemplate) -> FieldMapper:
	"""Clone ``FieldMapper`` with the template's keyword overrides merged."""
	mapper = FieldMapper()
	# Shallow copy so we don't mutate the class-level table
	base = dict(FieldMapper.FIELD_KEYWORDS.get(template.target_doctype, {}))
	for keyword, fieldname in template.field_mappings.items():
		base.setdefault(fieldname, [])
		if keyword not in base[fieldname]:
			base[fieldname] = [*base[fieldname], keyword]
	# Install per-instance override
	mapper.FIELD_KEYWORDS = {  # type: ignore[assignment]
		**FieldMapper.FIELD_KEYWORDS,
		template.target_doctype: base,
	}
	return mapper


def _merge_template_hits(
	mapper: FieldMapper,
	extracted: ExtractionResult,
	template: LoadedTemplate,
	mapped: MappedDocument,
) -> None:
	"""Scan text for template keywords and fill fields not already mapped."""
	text = extracted.text or ""
	for keyword, fieldname in template.field_mappings.items():
		if fieldname in mapped.header:
			continue
		value = _extract_value_near(text, keyword)
		if value:
			schema_fields: list[dict] = []  # unused: normaliser handles gracefully
			mapped.header[fieldname] = mapper._normalise_value(value, fieldname, schema_fields)
			mapped.confidence_scores[fieldname] = 0.65
			logger.debug(f"Template override filled {fieldname}={value!r} via keyword {keyword!r}")


def _extract_value_near(text: str, keyword: str) -> str | None:
	"""Grab the token(s) immediately following *keyword* on the same line."""
	for line in text.splitlines():
		if keyword.lower() in line.lower():
			idx = line.lower().index(keyword.lower()) + len(keyword)
			tail = line[idx:].lstrip(" :\t-")
			if tail:
				return tail.strip()
	return None


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def match_and_apply(
	extracted: ExtractionResult,
	target_doctype: str,
	*,
	company: str | None = None,
) -> tuple[MappedDocument, LoadedTemplate | None]:
	"""Detect a template, run mapping, return ``(mapped, template_or_None)``.

	Falls back to the plain :class:`FieldMapper` when no template matches.
	"""
	template = detect_template(extracted, target_doctype)
	if template is None:
		mapped = FieldMapper().map_fields(extracted, target_doctype, company=company)
		return mapped, None
	mapped = apply_template(template, extracted, company=company)
	return mapped, template
