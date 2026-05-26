# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 28 — Token-Efficiency Deep Cuts: unit tests.

Pure-mode tests (no Frappe site required) covering:

* G1 — page_prepass.select_relevant_pages
* G2 — hybrid mapper output cache helpers (_build_mapper_cache_key /
        _mapped_to_dict / _dict_to_mapped roundtrip)
* G3 — extractor.needs_vision_fallback
* G4 — summariser.maybe_summarise threshold + tail behaviour
* G5 — message_renderer.strip_thinking

The mapper-cache hit/miss path that crosses Frappe is exercised in the
bench test suite — pure-mode here verifies the deterministic helpers
that the integration relies on.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# G1 — page-aware pre-pass
# ---------------------------------------------------------------------------


class TestPagePrepass:
	def test_keeps_pages_with_money_and_dates(self):
		from idp.llm.page_prepass import select_relevant_pages

		text = (
			"--- Page 1 ---\n"
			"Invoice no INV/2026/0001\n"
			"Date: 22-Apr-2026\n"
			"Total: Rs 1,250.00\n"
			"--- Page 2 ---\n"
			"This is just boilerplate copyright text with no signal.\n"
		)
		filtered, stats = select_relevant_pages(text, "Sales Invoice")
		assert "INV/2026/0001" in filtered
		assert "boilerplate copyright text" not in filtered or "omitted" in filtered
		assert stats["pages_total"] == 2
		assert stats["pages_kept"] >= 1
		assert stats["chars_after"] <= stats["chars_total"]

	def test_keeps_all_when_no_page_markers(self):
		from idp.llm.page_prepass import select_relevant_pages

		text = "Invoice no INV/2026/0001\nTotal: 1,250.00"
		filtered, stats = select_relevant_pages(text, "Sales Invoice")
		# No page dividers → body returned unchanged; nothing to elide.
		assert filtered == text
		assert stats["pages_total"] == 0
		assert stats["pages_omitted"] == 0
		# chars_total reflects the input length so the renderer can
		# still record ``attachment_text_chars_total`` accurately.
		assert stats["chars_total"] == len(text)

	def test_unknown_doctype_falls_back_to_generic(self):
		from idp.llm.page_prepass import select_relevant_pages

		text = "--- Page 1 ---\n12/04/2026 Total 1,250\n--- Page 2 ---\nxxxxxx"
		filtered, _ = select_relevant_pages(text, "Some Unknown DocType")
		assert "12/04/2026" in filtered

	def test_extra_patterns_supplement_builtins(self):
		from idp.llm.page_prepass import select_relevant_pages

		text = "--- Page 1 ---\nPO-XYZ-987\n--- Page 2 ---\nnothing\n"
		filtered, stats = select_relevant_pages(
			text,
			"Sales Invoice",
			extra_patterns=[r"PO-[A-Z]+-\d+"],
		)
		assert "PO-XYZ-987" in filtered
		assert stats["pages_kept"] == 1


# ---------------------------------------------------------------------------
# G2 — mapper cache helpers
# ---------------------------------------------------------------------------


class TestMapperCacheHelpers:
	def test_cache_key_is_stable(self):
		from idp.mappers.hybrid_mapper import _build_mapper_cache_key

		k1 = _build_mapper_cache_key("abc", "Sales Invoice", 1)
		k2 = _build_mapper_cache_key("abc", "Sales Invoice", 1)
		assert k1 == k2
		assert "Sales Invoice" in k1
		assert "abc" in k1

	def test_cache_key_changes_with_mapper_version(self):
		from idp.mappers.hybrid_mapper import _build_mapper_cache_key

		k1 = _build_mapper_cache_key("abc", "Sales Invoice", 1)
		k2 = _build_mapper_cache_key("abc", "Sales Invoice", 2)
		assert k1 != k2

	def test_mapped_dict_roundtrip(self):
		from idp.mappers.base import MappedDocument
		from idp.mappers.hybrid_mapper import _dict_to_mapped, _mapped_to_dict

		original = MappedDocument(
			doctype="Sales Invoice",
			header={"customer": "ACME"},
			items=[{"item_code": "X-1", "qty": 2}],
			confidence_scores={"customer": {"score": 0.9, "source": "rule"}},
			warnings=["hybrid: rule pass sufficient"],
		)
		blob = _mapped_to_dict(original)
		assert blob["header"]["customer"] == "ACME"
		hydrated = _dict_to_mapped(blob)
		assert hydrated.doctype == original.doctype
		assert hydrated.header == original.header
		assert hydrated.items == original.items
		assert hydrated.warnings == original.warnings


# ---------------------------------------------------------------------------
# G3 — vision-gating heuristic
# ---------------------------------------------------------------------------


class TestVisionGating:
	def test_short_text_triggers_fallback(self, monkeypatch):
		# Stub the IDP Settings read so the test is hermetic.
		from idp.extractors import extractor as ex

		monkeypatch.setattr(ex, "_read_vision_gating_settings", lambda: (200, 0.05))
		assert ex.needs_vision_fallback("hello world", page_count=2) is True

	def test_rich_text_skips_fallback(self, monkeypatch):
		from idp.extractors import extractor as ex

		monkeypatch.setattr(ex, "_read_vision_gating_settings", lambda: (200, 0.05))
		body = (
			"Invoice no INV/2026/0001 dated 22-Apr-2026.  Customer: ACME Pvt Ltd. "
			"Items: widget x10 at Rs 100 each.  Total payable Rs 1,250.00.  "
			"Thank you for your business.  Terms: net-30."
		) * 4
		assert ex.needs_vision_fallback(body, page_count=1) is False

	def test_alphanumeric_ratio_below_threshold(self, monkeypatch):
		from idp.extractors import extractor as ex

		monkeypatch.setattr(ex, "_read_vision_gating_settings", lambda: (50, 0.5))
		junk = "..." * 200 + "a"  # >50 chars but mostly punctuation
		assert ex.needs_vision_fallback(junk, page_count=1) is True


# ---------------------------------------------------------------------------
# G4 — summariser
# ---------------------------------------------------------------------------


class TestSummariser:
	def _rows(self, n: int) -> list[dict]:
		out: list[dict] = []
		for i in range(1, n + 1):
			role = "user" if i % 2 else "assistant"
			out.append(
				{
					"name": f"msg-{i}",
					"role": role,
					"content": f"message body {i}",
					"sequence": i,
				}
			)
		return out

	def test_below_threshold_returns_passthrough(self, monkeypatch):
		from idp.llm import summariser

		monkeypatch.setattr(summariser, "_read_summariser_settings", lambda: (8, 4))
		result = summariser.maybe_summarise(
			conversation_id="conv-1",
			rows=self._rows(3),
			llm_client=None,
		)
		assert result["digest"] == ""
		assert len(result["tail"]) == 3

	def test_above_threshold_calls_llm_and_keeps_tail(self, monkeypatch):
		from idp.llm import summariser

		monkeypatch.setattr(summariser, "_read_summariser_settings", lambda: (4, 2))
		monkeypatch.setattr(summariser, "_load_persisted_digest", lambda _c: ("", 0))
		persisted_calls: list[tuple] = []
		monkeypatch.setattr(
			summariser,
			"_persist_digest",
			lambda c, d, s: persisted_calls.append((c, d, s)),
		)

		class _Resp:
			content = "Compressed dialogue: user uploaded invoice; assistant proposed mapping."

		client = MagicMock()
		client.chat = MagicMock(return_value=_Resp())

		result = summariser.maybe_summarise(
			conversation_id="conv-2",
			rows=self._rows(8),
			llm_client=client,
		)
		assert result["digest"].startswith("Compressed dialogue")
		# Tail is the last keep_recent rows verbatim.
		assert len(result["tail"]) == 2
		# Durable cache was written.
		assert persisted_calls and persisted_calls[0][0] == "conv-2"

	def test_persisted_digest_short_circuits_llm(self, monkeypatch):
		from idp.llm import summariser

		monkeypatch.setattr(summariser, "_read_summariser_settings", lambda: (4, 2))
		monkeypatch.setattr(
			summariser,
			"_load_persisted_digest",
			lambda _c: ("cached digest text", 6),
		)
		client = MagicMock()
		result = summariser.maybe_summarise(
			conversation_id="conv-3",
			rows=self._rows(8),
			llm_client=client,
		)
		assert result["digest"] == "cached digest text"
		client.chat.assert_not_called()


# ---------------------------------------------------------------------------
# G5 — strip thinking blocks
# ---------------------------------------------------------------------------


class TestStripThinking:
	def test_removes_thinking_block(self):
		from idp.llm.message_renderer import strip_thinking

		content = "<thinking>step 1\nstep 2</thinking>Final answer: 42."
		assert strip_thinking(content) == "Final answer: 42."

	def test_removes_lowercase_and_uppercase(self):
		from idp.llm.message_renderer import strip_thinking

		assert (
			strip_thinking("<THINK>foo</THINK>bar").strip() == "bar"
		)

	def test_passes_through_when_no_blocks(self):
		from idp.llm.message_renderer import strip_thinking

		txt = "Plain text without any blocks."
		assert strip_thinking(txt) == txt

	def test_handles_multiple_blocks(self):
		from idp.llm.message_renderer import strip_thinking

		content = (
			"<thinking>a</thinking>step1\n"
			"<think>b</think>step2"
		)
		out = strip_thinking(content)
		assert "thinking" not in out.lower() or "<think" not in out
		assert "step1" in out and "step2" in out


# ---------------------------------------------------------------------------
# G6 — per-tool max_output_tokens enforcement
# ---------------------------------------------------------------------------


class TestPerToolMaxOutputTokens:
	def test_under_cap_passes_through(self):
		from idp.tools.base import ToolResult
		from idp.tools.registry import _enforce_output_cap

		small = ToolResult.ok({"rows": [1, 2, 3]})
		out = _enforce_output_cap(small, "any_tool", max_tokens=100)
		assert out is small  # untouched

	def test_over_cap_truncates_and_stops(self):
		from idp.tools.base import ToolResult
		from idp.tools.registry import _enforce_output_cap

		big = ToolResult.ok({"blob": "x" * 5000, "count": 999})
		out = _enforce_output_cap(big, "list_documents", max_tokens=50)
		assert out.success is True
		assert out.stop_processing is True
		assert out.error_code == "OUTPUT_TOO_LARGE"
		assert isinstance(out.data, dict) and out.data.get("truncated") is True
		# Preserved shallow fields make it through.
		assert out.data.get("count") == 999

	def test_failure_envelope_not_measured(self):
		from idp.tools.base import ToolResult
		from idp.tools.registry import _enforce_output_cap

		err = ToolResult.fail("bad input", error_code="VALIDATION_FAILED")
		out = _enforce_output_cap(err, "any_tool", max_tokens=10)
		assert out is err
