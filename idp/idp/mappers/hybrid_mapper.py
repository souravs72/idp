# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Hybrid rule + LLM field mapper (Phase 16).

Strategy:

1. Run the deterministic :class:`FieldMapper` first.
2. If every required field is filled and the average confidence is at
   or above the configured threshold, return the rule mapping verbatim
   (free, fast, deterministic).
3. Otherwise call the LLM via :class:`LLMClient` with the field-mapping
   tool schema, and merge the response back in **without overwriting**
   high-confidence rule values.
4. Tag every field with provenance (``rule`` / ``template`` / ``llm``)
   in :attr:`MappedDocument.confidence_scores` so downstream UIs and
   audits can see which side won.
5. On any LLM failure, return the rule-only mapping with a warning —
   the hybrid mapper must never make extraction *less* reliable than
   the rule mapper alone.
"""

from __future__ import annotations

from typing import Any

from idp.core.exceptions import LLMError
from idp.core.logger import get_logger
from idp.idp.llm.prompts import build_system_prompt, build_user_message
from idp.idp.llm.schemas import FIELD_MAPPING_TOOL_SCHEMA
from idp.idp.mappers.base import MappedDocument

logger = get_logger("idp.mappers.hybrid")

DEFAULT_THRESHOLD = 0.70


class HybridFieldMapper:
	"""Combine the rule mapper with an LLM fallback below threshold."""

	def __init__(
		self,
		rule_mapper: Any,
		llm_client: Any,
		*,
		confidence_threshold: float = DEFAULT_THRESHOLD,
	) -> None:
		self.rule_mapper = rule_mapper
		self.llm_client = llm_client
		self.confidence_threshold = confidence_threshold

	def map_fields(
		self,
		extracted: Any,
		target_doctype: str,
		*,
		company: str | None = None,
		output_language: str = "English",
		industry: str | None = None,
		user: str | None = None,
		source_lang: str | None = None,
	) -> MappedDocument:
		# --- 1. Rule-based pass --------------------------------------------------
		rule_kwargs: dict[str, Any] = {"company": company}
		if source_lang:
			rule_kwargs["source_lang"] = source_lang
		try:
			rule_result = self.rule_mapper.map_fields(extracted, target_doctype, **rule_kwargs)
		except TypeError:
			# Backwards compatible with older mappers that don't accept
			# the ``source_lang`` keyword (e.g. tests with stub mappers).
			rule_result = self.rule_mapper.map_fields(extracted, target_doctype, company=company)
		_tag_provenance(rule_result, source="rule")

		# --- 2. Decide whether to invoke the LLM --------------------------------
		schema_required = _required_fieldnames(target_doctype)
		missing = [f for f in schema_required if f not in rule_result.header]
		avg_conf = _avg_confidence(rule_result)
		if not missing and avg_conf >= self.confidence_threshold:
			rule_result.warnings.append(
				f"hybrid: rule pass sufficient (avg_conf={avg_conf:.2f} >= {self.confidence_threshold:.2f})"
			)
			return rule_result

		# --- 3. LLM fallback -----------------------------------------------------
		try:
			llm_payload = self._call_llm(
				extracted,
				target_doctype,
				partial=rule_result,
				output_language=output_language,
				industry=industry,
				user=user,
			)
		except LLMError as exc:
			logger.warning(f"LLM fallback failed; returning rule-only mapping: {exc}")
			rule_result.warnings.append(f"hybrid: llm unavailable ({exc}); rule-only mapping returned")
			# Even when the mapping LLM call fails we still try the
			# narrative translator — it has its own retry / cache and is
			# typically a different prompt that can succeed independently.
			_translate_narrative(
				rule_result,
				source_lang=source_lang,
				output_language=output_language,
				llm_client=self.llm_client,
			)
			return rule_result

		# --- 4. Merge ------------------------------------------------------------
		merged = self._merge(rule_result, llm_payload)
		merged.warnings.append(
			f"hybrid: llm fallback applied (rule_avg={avg_conf:.2f}, missing_required={len(missing)})"
		)
		# --- 5. Phase 22 — translate narrative fields ---------------------------
		_translate_narrative(
			merged,
			source_lang=source_lang,
			output_language=output_language,
			llm_client=self.llm_client,
		)
		return merged

	# ------------------------------------------------------------------------
	# internals
	# ------------------------------------------------------------------------

	def _call_llm(
		self,
		extracted: Any,
		target_doctype: str,
		*,
		partial: MappedDocument,
		output_language: str,
		industry: str | None,
		user: str | None,
	) -> dict:
		system = build_system_prompt(target_doctype, industry=industry, output_language=output_language)
		user_msg = build_user_message(
			_extracted_to_dict(extracted),
			partial_mapping={"header": partial.header, "items": partial.items},
		)
		response = self.llm_client.chat(
			messages=[
				{"role": "system", "content": system},
				{"role": "user", "content": user_msg},
			],
			tools=[FIELD_MAPPING_TOOL_SCHEMA],
			tool_choice="auto",
			user=user,
		)
		if not response.tool_calls:
			# Some providers return JSON mode content instead of a tool call;
			# accept that path too.
			if response.content:
				import json as _json

				try:
					return _json.loads(response.content)
				except ValueError:
					pass
			raise LLMError("LLM returned no tool call and no parsable JSON content")
		return response.tool_calls[0].arguments or {}

	def _merge(self, rule_result: MappedDocument, llm_payload: dict) -> MappedDocument:
		llm_header = llm_payload.get("header") or {}
		llm_items = llm_payload.get("items") or []
		llm_conf = llm_payload.get("confidence_scores") or {}
		llm_warnings = llm_payload.get("warnings") or []

		merged = MappedDocument(
			doctype=rule_result.doctype,
			header=dict(rule_result.header),
			items=list(rule_result.items),
			unmapped_fields=list(rule_result.unmapped_fields),
			confidence_scores=dict(rule_result.confidence_scores),
			warnings=list(rule_result.warnings),
			link_resolutions=dict(rule_result.link_resolutions),
		)

		for fieldname, value in llm_header.items():
			rule_score = _score_of(merged.confidence_scores.get(fieldname))
			llm_score = float(llm_conf.get(fieldname, 0.5) or 0.0)
			# Only overwrite when the LLM is meaningfully more confident OR
			# when the rule mapper produced no value at all.
			if fieldname not in merged.header or llm_score > rule_score:
				merged.header[fieldname] = value
				merged.confidence_scores[fieldname] = {"score": llm_score, "source": "llm"}

		# Items: trust the LLM only when the rule mapper produced none —
		# table extraction is hard to merge generically and the rule path
		# is much more reliable when it works.
		if not merged.items and llm_items:
			merged.items = list(llm_items)

		for w in llm_warnings:
			if isinstance(w, str):
				merged.warnings.append(f"llm: {w}")
		return merged


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _tag_provenance(result: MappedDocument, *, source: str) -> None:
	"""Wrap each scalar score in ``{score, source}`` for downstream introspection."""

	for field, score in list(result.confidence_scores.items()):
		if isinstance(score, dict):
			score.setdefault("source", source)
		else:
			result.confidence_scores[field] = {"score": float(score or 0.0), "source": source}


def _score_of(entry: Any) -> float:
	if isinstance(entry, dict):
		return float(entry.get("score", 0.0) or 0.0)
	try:
		return float(entry or 0.0)
	except (TypeError, ValueError):
		return 0.0


def _avg_confidence(result: MappedDocument) -> float:
	scores = [_score_of(v) for v in result.confidence_scores.values()]
	if not scores:
		return 0.0
	return sum(scores) / len(scores)


def _required_fieldnames(target_doctype: str) -> list[str]:
	try:
		from idp.idp.mappers.base import get_doctype_schema

		schema = get_doctype_schema(target_doctype)
	except Exception as exc:
		logger.debug(f"required-field lookup skipped for {target_doctype}: {exc}")
		return []
	return [f["fieldname"] for f in schema.get("fields") or [] if f.get("reqd")]


def _extracted_to_dict(extracted: Any) -> dict:
	"""Render an ExtractionResult-ish object as a JSON-safe dict for prompts."""

	if isinstance(extracted, dict):
		return extracted
	out: dict[str, Any] = {}
	for attr in ("text", "tables", "metadata", "key_values"):
		if hasattr(extracted, attr):
			val = getattr(extracted, attr)
			if val is not None:
				out[attr] = val
	return out or {"text": str(extracted)}


def _translate_narrative(
	mapped: MappedDocument,
	*,
	source_lang: str | None,
	output_language: str,
	llm_client: Any,
) -> None:
	"""Translate narrative header fields in *mapped* in place.

	No-op when:
	* ``source_lang`` is missing or already matches ``output_language``.
	* The translation module isn't importable.
	* The LLM client is None or throws — see :mod:`translation` for the
	  graceful-degradation contract.
	"""

	if not source_lang or not output_language:
		return
	try:
		from idp.idp.llm.translation import translate_mapping
		from idp.idp.mappers.keywords_ml import normalize_language
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"translation skipped: import failed ({exc})")
		return

	src = normalize_language(source_lang)
	tgt = normalize_language(output_language)
	if not src or not tgt or src == tgt:
		return

	try:
		swaps = translate_mapping(
			mapped.header,
			source_lang=src,
			target_lang=tgt,
			llm_client=llm_client,
		)
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug(f"translation aborted in hybrid mapper: {exc}")
		return

	if not swaps:
		return
	for fieldname, payload in swaps.items():
		# Mark provenance so the ConfirmationCard UI can flag the
		# translated copy and offer "show original".
		entry = mapped.confidence_scores.get(fieldname)
		if isinstance(entry, dict):
			entry["translated_from"] = src
			entry["translated_to"] = tgt
			entry["original_text"] = payload.get("original")
		else:
			mapped.confidence_scores[fieldname] = {
				"score": _score_of(entry),
				"source": "translation",
				"translated_from": src,
				"translated_to": tgt,
				"original_text": payload.get("original"),
			}
	mapped.warnings.append(f"hybrid: translated {len(swaps)} narrative field(s) {src} → {tgt}")


__all__ = ["HybridFieldMapper"]
