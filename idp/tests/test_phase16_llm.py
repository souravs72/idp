# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Phase 16 unit tests — LLM provider abstraction & hybrid mapper.

Covers the three Phase-16 deliverables that were missing from the
pre-existing v1 implementation:

* Anthropic prompt caching (``cache_control: ephemeral`` on system + tools).
* Two-tier model routing via ``LLMClient.resolve_route`` + ``chat(purpose=...)``.
* Per-DocType ``llm_fallback_threshold`` resolution in ``HybridFieldMapper``.

Tests are pure-mode: no Frappe site required.  Provider classes are
stubbed where needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from idp.llm.providers.anthropic_provider import (
	AnthropicProvider,
	_wrap_system_with_cache,
	_wrap_tools_with_cache,
	translate_tools_openai_to_anthropic,
)
from idp.llm.providers.base import LLMResponse, TokenUsage, ToolCall
from idp.llm.client import LLMClient, _normalise_routes


# ---------------------------------------------------------------------------
# Anthropic cache_control
# ---------------------------------------------------------------------------


def test_wrap_system_with_cache_emits_ephemeral_block():
	wrapped = _wrap_system_with_cache("You are a helpful assistant.")
	assert isinstance(wrapped, list)
	assert wrapped[0]["type"] == "text"
	assert wrapped[0]["text"] == "You are a helpful assistant."
	assert wrapped[0]["cache_control"] == {"type": "ephemeral"}


def test_wrap_tools_with_cache_marks_last_tool_only():
	tools = [{"name": "a", "input_schema": {}}, {"name": "b", "input_schema": {}}]
	out = _wrap_tools_with_cache(tools)
	assert "cache_control" not in out[0]
	assert out[-1]["cache_control"] == {"type": "ephemeral"}
	# Original list untouched (copy semantics).
	assert "cache_control" not in tools[-1]


def test_wrap_tools_with_cache_empty_passthrough():
	assert _wrap_tools_with_cache([]) == []


def test_anthropic_default_model_is_opus_4_5():
	provider = AnthropicProvider(api_key="key-redacted")
	assert provider.default_model == "claude-opus-4-5-20251101"


class _FakeAnthropicMessages:
	"""Records the payload passed to ``messages.create`` for assertion."""

	def __init__(self, recorder: list[dict]):
		self.recorder = recorder

	def create(self, **payload):
		self.recorder.append(payload)

		class _Resp:
			def model_dump(self_inner):
				return {
					"content": [{"type": "text", "text": "ok"}],
					"stop_reason": "stop",
					"usage": {
						"input_tokens": 10,
						"output_tokens": 5,
						"cache_read_input_tokens": 7,
						"cache_creation_input_tokens": 3,
					},
				}

		return _Resp()


class _FakeAnthropicClient:
	def __init__(self, recorder: list[dict]):
		self.messages = _FakeAnthropicMessages(recorder)


def test_anthropic_chat_wraps_system_and_tools_when_cache_enabled():
	provider = AnthropicProvider(api_key="key", cache_control=True)
	recorder: list[dict] = []
	provider._client = _FakeAnthropicClient(recorder)

	tools = [
		{"type": "function", "function": {"name": "echo", "parameters": {}}},
	]
	provider.chat(
		messages=[
			{"role": "system", "content": "Static system prompt"},
			{"role": "user", "content": "hi"},
		],
		tools=tools,
	)

	payload = recorder[0]
	# System wrapped in ephemeral text block.
	assert isinstance(payload["system"], list)
	assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
	# Tools translated and last tool marked.
	assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_chat_skips_cache_when_disabled_per_call():
	provider = AnthropicProvider(api_key="key", cache_control=True)
	recorder: list[dict] = []
	provider._client = _FakeAnthropicClient(recorder)

	provider.chat(
		messages=[
			{"role": "system", "content": "ephemeral one-off prompt"},
			{"role": "user", "content": "hi"},
		],
		tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
		cache_control=False,
	)

	payload = recorder[0]
	assert payload["system"] == "ephemeral one-off prompt"
	# Tools still translated but NOT wrapped.
	assert "cache_control" not in payload["tools"][-1]


def test_anthropic_normalise_surfaces_cached_tokens():
	provider = AnthropicProvider(api_key="key")
	recorder: list[dict] = []
	provider._client = _FakeAnthropicClient(recorder)
	resp = provider.chat(
		messages=[{"role": "user", "content": "hi"}],
	)
	assert resp.raw["_idp_cached_tokens"] == 7
	assert resp.raw["_idp_cache_creation_tokens"] == 3


# ---------------------------------------------------------------------------
# LLMClient two-tier routing
# ---------------------------------------------------------------------------


class _StubProvider:
	name = "stub"
	default_model = "stub-default"

	def __init__(self, label: str = "stub"):
		self.label = label
		self.calls: list[dict] = []

	def chat(self, messages, **kwargs):
		self.calls.append({"messages": messages, **kwargs})
		return LLMResponse(
			content="ok",
			tool_calls=[],
			finish_reason="stop",
			usage=TokenUsage(prompt=1, completion=1),
			raw={},
			model=kwargs.get("model") or self.default_model,
			provider=self.label,
		)

	def count_tokens(self, messages, *, model=None):
		return 1


def test_resolve_route_returns_default_when_no_purpose():
	default = _StubProvider("default")
	client = LLMClient(default, default_model="m-default", routes=[])
	provider, model = client.resolve_route(None)
	assert provider is default
	assert model == "m-default"


def test_resolve_route_returns_default_when_no_route_matches():
	default = _StubProvider("default")
	routes = [{"purpose": "extraction", "provider": "anthropic", "model": "claude-opus", "tier": "expensive"}]
	client = LLMClient(default, default_model="m-default", routes=routes)
	provider, model = client.resolve_route("vision")
	assert provider is default
	assert model == "m-default"


def test_resolve_route_matches_purpose():
	default = _StubProvider("default")
	# Pre-seed cache so we don't actually try to build a real provider.
	custom = _StubProvider("custom")
	routes = [
		{"purpose": "classification", "provider": "custom", "model": "haiku", "tier": "cheap"},
		{"purpose": "extraction", "provider": "custom", "model": "opus", "tier": "expensive"},
	]
	client = LLMClient(default, default_model="m-default", routes=routes)
	client._provider_cache["custom"] = custom
	provider, model = client.resolve_route("extraction")
	assert provider is custom
	assert model == "opus"


def test_chat_routes_to_cheap_tier_when_purpose_supplied():
	default = _StubProvider("default")
	cheap = _StubProvider("cheap")
	routes = [{"purpose": "classification", "provider": "cheap", "model": "haiku", "tier": "cheap"}]
	client = LLMClient(default, default_model="m-default", routes=routes)
	client._provider_cache["cheap"] = cheap
	resp = client.chat([{"role": "user", "content": "hi"}], purpose="classification")
	assert resp.provider == "cheap"
	assert cheap.calls and cheap.calls[0]["model"] == "haiku"
	assert not default.calls


def test_chat_explicit_model_overrides_routing():
	default = _StubProvider("default")
	cheap = _StubProvider("cheap")
	routes = [{"purpose": "classification", "provider": "cheap", "model": "haiku", "tier": "cheap"}]
	client = LLMClient(default, default_model="m-default", routes=routes)
	client._provider_cache["cheap"] = cheap
	# Explicit model wins over purpose-based routing.
	resp = client.chat(
		[{"role": "user", "content": "hi"}],
		model="gpt-4o-mini",
		purpose="classification",
	)
	assert resp.provider == "default"
	assert default.calls[0]["model"] == "gpt-4o-mini"
	assert not cheap.calls


def test_chat_annotates_purpose_in_raw_envelope():
	default = _StubProvider("default")
	client = LLMClient(default, default_model="m-default", routes=[])
	resp = client.chat([{"role": "user", "content": "hi"}], purpose="summarisation")
	assert resp.raw["_idp_purpose"] == "summarisation"


# ---------------------------------------------------------------------------
# Route normalisation
# ---------------------------------------------------------------------------


def test_normalise_routes_skips_incomplete_rows():
	rows = [
		{"purpose": "extraction", "provider": "", "model_name": "opus"},
		{"purpose": "classification", "provider": "anthropic", "model_name": "haiku", "tier": "cheap"},
		{"purpose": "", "provider": "anthropic", "model_name": "opus"},
	]
	out = _normalise_routes(rows)
	assert out == [
		{"purpose": "classification", "provider": "anthropic", "model": "haiku", "tier": "cheap"},
	]


def test_normalise_routes_defaults_tier_to_expensive():
	rows = [{"purpose": "extraction", "provider": "anthropic", "model_name": "opus"}]
	out = _normalise_routes(rows)
	assert out[0]["tier"] == "expensive"


def test_normalise_routes_strips_whitespace():
	rows = [{"purpose": " extraction ", "provider": "anthropic", "model_name": " opus "}]
	out = _normalise_routes(rows)
	assert out[0]["purpose"] == "extraction"
	assert out[0]["model"] == "opus"


# ---------------------------------------------------------------------------
# Hybrid mapper per-DocType threshold
# ---------------------------------------------------------------------------


def test_hybrid_mapper_uses_explicit_doctype_override():
	from idp.mappers.hybrid_mapper import HybridFieldMapper

	mapper = HybridFieldMapper(
		rule_mapper=object(),
		llm_client=object(),
		confidence_threshold=0.70,
		doctype_thresholds={"Purchase Invoice": 0.85},
	)
	assert mapper._resolve_threshold("Purchase Invoice") == 0.85
	# Unrelated doctype falls back to instance default.
	assert mapper._resolve_threshold("Sales Order") == 0.70


def test_hybrid_mapper_falls_back_to_instance_threshold_when_frappe_absent(monkeypatch):
	from idp.mappers import hybrid_mapper as hm

	# Force the inner frappe.get_all path to raise so we hit the fallback.
	class _BoomFrappe:
		def get_all(self, *_a, **_kw):
			raise RuntimeError("no site")

	monkeypatch.setitem(__import__("sys").modules, "frappe", _BoomFrappe())

	mapper = hm.HybridFieldMapper(
		rule_mapper=object(),
		llm_client=object(),
		confidence_threshold=0.60,
	)
	assert mapper._resolve_threshold("Purchase Invoice") == 0.60


# ---------------------------------------------------------------------------
# IDP Extraction Template DocType JSON
# ---------------------------------------------------------------------------


ROOT = Path(__file__).resolve().parents[2]
EXTRACTION_TEMPLATE = ROOT / "idp/idp/doctype/idp_extraction_template/idp_extraction_template.json"


def test_extraction_template_has_llm_fallback_threshold():
	data = json.loads(EXTRACTION_TEMPLATE.read_text())
	fields = {f["fieldname"]: f for f in data["fields"]}
	assert "llm_fallback_threshold" in fields
	field = fields["llm_fallback_threshold"]
	assert field["fieldtype"] == "Float"
	assert field["label"] == "LLM Fallback Threshold"


def test_extraction_template_llm_section_present():
	data = json.loads(EXTRACTION_TEMPLATE.read_text())
	order = data["field_order"]
	assert "llm_section" in order
	assert "llm_fallback_threshold" in order
	# Section must precede the field.
	assert order.index("llm_section") < order.index("llm_fallback_threshold")
