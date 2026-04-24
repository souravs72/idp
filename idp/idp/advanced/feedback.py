# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.3 — Learning & feedback loop.

Record user corrections on extracted field values, aggregate them per
supplier/customer/DocType, and expose two downstream uses:

1. **Few-shot prompt builder** -- turn recent corrections into
   ``"input -> output"`` exemplars that can be appended to an LLM
   system prompt on subsequent extractions.
2. **Rule-mapper keyword tuning** -- find labels that the
   :class:`FieldMapper` consistently gets wrong and surface them so
   they can be added to :data:`FieldMapper.FIELD_KEYWORDS`.

This module is backend-only; a frontend review screen records
corrections via :func:`record_correction`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import frappe

from idp.core.logger import get_logger

logger = get_logger("idp.advanced.feedback")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def record_correction(
	user: str,
	target_doctype: str,
	fieldname: str,
	extracted_value: Any,
	corrected_value: Any,
	*,
	source_file_url: str | None = None,
	source_text_snippet: str | None = None,
	supplier_or_customer: str | None = None,
	template_used: str | None = None,
	origin: str = "rule",
) -> str:
	"""Persist one correction and return its doc name.

	No-ops (empty corrected value, or corrected == extracted) are rejected
	to keep the dataset clean.
	"""
	if corrected_value in (None, ""):
		raise ValueError("record_correction: corrected_value cannot be empty")

	if str(extracted_value).strip() == str(corrected_value).strip():
		raise ValueError("record_correction: extracted and corrected values are identical")

	if origin not in ("rule", "llm", "template", "manual"):
		origin = "rule"

	doc = frappe.new_doc("IDP Extraction Correction")
	doc.user = user
	doc.target_doctype = target_doctype
	doc.fieldname = fieldname
	doc.extracted_value = _to_text(extracted_value)
	doc.corrected_value = _to_text(corrected_value)
	doc.source_file_url = source_file_url
	doc.source_text_snippet = (source_text_snippet or "")[:4000]
	doc.supplier_or_customer = supplier_or_customer
	doc.template_used = template_used
	doc.origin = origin
	doc.insert(ignore_permissions=False)
	logger.info(
		f"Correction {doc.name} recorded: {target_doctype}.{fieldname} "
		f"{extracted_value!r} -> {corrected_value!r} (supplier={supplier_or_customer})"
	)
	return doc.name


def _to_text(value: Any) -> str:
	if value is None:
		return ""
	return str(value)


# ---------------------------------------------------------------------------
# Few-shot prompt builder
# ---------------------------------------------------------------------------


@dataclass
class FewShotExample:
	"""One prompt exemplar."""

	fieldname: str
	source_snippet: str
	corrected_value: str
	supplier_or_customer: str | None = None

	def as_prompt_line(self) -> str:
		"""Format as a single ``Input -> Output`` exemplar."""
		ctx = f" (supplier={self.supplier_or_customer})" if self.supplier_or_customer else ""
		snippet = self.source_snippet.replace("\n", " ").strip()
		if len(snippet) > 300:
			snippet = snippet[:297] + "..."
		return f"- field `{self.fieldname}`{ctx}: input={snippet!r} -> output={self.corrected_value!r}"


@dataclass
class FewShotBundle:
	"""Grouped exemplars ready for prompt injection."""

	target_doctype: str
	examples: list[FewShotExample] = field(default_factory=list)

	def render(self, *, max_examples: int = 6) -> str:
		if not self.examples:
			return ""
		lines = [
			f"# Past user corrections for {self.target_doctype}",
			"Use these examples to guide field extraction:",
		]
		for ex in self.examples[:max_examples]:
			lines.append(ex.as_prompt_line())
		return "\n".join(lines)


def build_fewshot_bundle(
	target_doctype: str,
	*,
	supplier_or_customer: str | None = None,
	max_examples: int = 6,
) -> FewShotBundle:
	"""Pull recent corrections and turn them into a prompt bundle.

	Examples are preferred when ``supplier_or_customer`` matches; otherwise
	the most recent corrections for the DocType are used as a fallback.
	Each (fieldname, supplier) pair contributes at most one exemplar to
	avoid prompt bloat.
	"""
	bundle = FewShotBundle(target_doctype=target_doctype)
	seen: set[tuple[str, str | None]] = set()

	filters: dict[str, Any] = {"target_doctype": target_doctype}
	if supplier_or_customer:
		filters["supplier_or_customer"] = supplier_or_customer

	rows = frappe.get_all(
		"IDP Extraction Correction",
		filters=filters,
		fields=["name", "fieldname", "corrected_value", "source_text_snippet", "supplier_or_customer"],
		order_by="modified desc",
		limit=max_examples * 3,
	)

	# Fallback: drop supplier filter if we came up empty
	if not rows and supplier_or_customer:
		rows = frappe.get_all(
			"IDP Extraction Correction",
			filters={"target_doctype": target_doctype},
			fields=["name", "fieldname", "corrected_value", "source_text_snippet", "supplier_or_customer"],
			order_by="modified desc",
			limit=max_examples * 3,
		)

	for row in rows:
		key = (row["fieldname"], row.get("supplier_or_customer"))
		if key in seen:
			continue
		seen.add(key)
		bundle.examples.append(
			FewShotExample(
				fieldname=row["fieldname"],
				source_snippet=row.get("source_text_snippet") or "",
				corrected_value=row.get("corrected_value") or "",
				supplier_or_customer=row.get("supplier_or_customer"),
			)
		)
		# Mark used so we can report accuracy trends later
		frappe.db.set_value(
			"IDP Extraction Correction", row["name"], "applied_to_fewshot", 1, update_modified=False
		)
		if len(bundle.examples) >= max_examples:
			break

	return bundle


# ---------------------------------------------------------------------------
# Rule-mapper tuning: where did we get it wrong?
# ---------------------------------------------------------------------------


def rule_mapper_weak_spots(target_doctype: str, *, min_occurrences: int = 3) -> list[dict]:
	"""Return fields for which the rule mapper has been corrected often.

	Output rows look like::

	    {"fieldname": "bill_no", "corrections": 7, "top_suppliers": ["Acme", "Globex"]}

	Useful as a report to guide which keywords should be added to
	:data:`FieldMapper.FIELD_KEYWORDS`.
	"""
	rows = frappe.get_all(
		"IDP Extraction Correction",
		filters={"target_doctype": target_doctype, "origin": "rule"},
		fields=["fieldname", "supplier_or_customer"],
		limit=10000,
	)
	field_counts = Counter(r["fieldname"] for r in rows)
	per_field_suppliers: dict[str, Counter] = {}
	for r in rows:
		fn = r["fieldname"]
		sup = r.get("supplier_or_customer")
		if not sup:
			continue
		per_field_suppliers.setdefault(fn, Counter())[sup] += 1

	weak: list[dict] = []
	for fieldname, count in field_counts.most_common():
		if count < min_occurrences:
			continue
		top = [s for s, _ in per_field_suppliers.get(fieldname, Counter()).most_common(3)]
		weak.append({"fieldname": fieldname, "corrections": count, "top_suppliers": top})
	return weak


# ---------------------------------------------------------------------------
# Accuracy trend
# ---------------------------------------------------------------------------


def accuracy_trend(target_doctype: str, *, days: int = 30) -> list[dict]:
	"""Count corrections per day over the last *days* days.

	A declining correction count indicates the pipeline is learning (or
	users are clicking through without correcting -- interpret with care).
	Returns ``[{"date": "YYYY-MM-DD", "corrections": n}, ...]``.
	"""
	result = frappe.db.sql(
		"""
		SELECT DATE(creation) AS d, COUNT(*) AS c
		FROM `tabIDP Extraction Correction`
		WHERE target_doctype = %(dt)s
		  AND creation >= DATE_SUB(NOW(), INTERVAL %(days)s DAY)
		GROUP BY DATE(creation)
		ORDER BY d ASC
		""",
		{"dt": target_doctype, "days": int(days)},
		as_dict=True,
	)
	return [{"date": str(row["d"]), "corrections": int(row["c"])} for row in result]
