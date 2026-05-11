# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Per-model capability and pricing registry.

Capabilities vary *per-model*, not per-provider — OpenAI alone ships
vision-capable, tool-capable, and plain-text models.  This registry
ships baseline entries for the models the app supports out of the box
and merges any admin-edited overrides from
``IDP Settings.model_overrides`` (JSON dict).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace

from idp.core.logger import get_logger

logger = get_logger("idp.llm.model_registry")


@dataclass
class ModelInfo:
	"""Merged baseline + override metadata for a single model id."""

	model_id: str
	provider: str
	context_window: int = 8_192
	supports_vision: bool = False
	supports_tools: bool = True
	supports_json_mode: bool = True
	input_cost_per_1k: float = 0.0
	output_cost_per_1k: float = 0.0


# Pricing is taken from public vendor rate cards at the time of writing.
# Admins should override via IDP Settings.model_overrides when vendors
# change prices or when new models are released between app versions.
_BASELINE: dict[str, ModelInfo] = {
	"gpt-4o": ModelInfo(
		model_id="gpt-4o",
		provider="openai",
		context_window=128_000,
		supports_vision=True,
		supports_tools=True,
		supports_json_mode=True,
		input_cost_per_1k=0.005,
		output_cost_per_1k=0.015,
	),
	"gpt-4o-mini": ModelInfo(
		model_id="gpt-4o-mini",
		provider="openai",
		context_window=128_000,
		supports_vision=True,
		supports_tools=True,
		supports_json_mode=True,
		input_cost_per_1k=0.00015,
		output_cost_per_1k=0.0006,
	),
	"claude-opus-4-5-20251101": ModelInfo(
		model_id="claude-opus-4-5-20251101",
		provider="anthropic",
		context_window=200_000,
		supports_vision=True,
		supports_tools=True,
		supports_json_mode=True,
		input_cost_per_1k=0.015,
		output_cost_per_1k=0.075,
	),
	"claude-haiku-4-5-20251001": ModelInfo(
		model_id="claude-haiku-4-5-20251001",
		provider="anthropic",
		context_window=200_000,
		supports_vision=True,
		supports_tools=True,
		supports_json_mode=True,
		input_cost_per_1k=0.001,
		output_cost_per_1k=0.005,
	),
	"llama3.1:8b": ModelInfo(
		model_id="llama3.1:8b",
		provider="ollama",
		context_window=32_768,
		supports_vision=False,
		supports_tools=False,
		supports_json_mode=True,
		input_cost_per_1k=0.0,
		output_cost_per_1k=0.0,
	),
	"mistral:7b": ModelInfo(
		model_id="mistral:7b",
		provider="ollama",
		context_window=32_768,
		supports_vision=False,
		supports_tools=False,
		supports_json_mode=True,
		input_cost_per_1k=0.0,
		output_cost_per_1k=0.0,
	),
}


_FIELD_NAMES = {f.name for f in fields(ModelInfo)}


def _load_overrides() -> dict[str, dict]:
	"""Load admin overrides from ``IDP Settings.model_overrides``.

	Returns an empty dict when the site is unreachable or the JSON is
	invalid — never raises.
	"""

	try:
		import frappe

		raw = frappe.db.get_single_value("IDP Settings", "model_overrides")
	except Exception as exc:
		logger.debug(f"model_overrides lookup skipped: {exc}")
		return {}

	if not raw:
		return {}

	try:
		data = json.loads(raw)
	except (ValueError, TypeError) as exc:
		logger.warning(f"IDP Settings.model_overrides is not valid JSON: {exc}")
		return {}

	if not isinstance(data, dict):
		logger.warning("IDP Settings.model_overrides must be a JSON object")
		return {}
	return data


def get_model_info(model_id: str) -> ModelInfo:
	"""Return merged baseline + override :class:`ModelInfo` for *model_id*.

	Unknown models fall back to a conservative default with zero cost so
	``estimate_cost`` never raises.
	"""

	overrides = _load_overrides()
	baseline = _BASELINE.get(model_id)
	override = overrides.get(model_id) if isinstance(overrides, dict) else None

	if baseline is None and override is None:
		logger.debug(f"Unknown model {model_id!r}; using conservative defaults")
		return ModelInfo(model_id=model_id, provider="unknown")

	if baseline is None:
		# Override-only entry: caller added a new model in IDP Settings.
		base = ModelInfo(model_id=model_id, provider=override.get("provider", "unknown"))
	else:
		base = baseline

	if override:
		patch = {k: v for k, v in override.items() if k in _FIELD_NAMES and k != "model_id"}
		return replace(base, **patch)
	return base


def list_known_models() -> list[ModelInfo]:
	"""Return merged baseline + overrides as a list of :class:`ModelInfo`."""

	overrides = _load_overrides()
	seen: dict[str, ModelInfo] = {mid: get_model_info(mid) for mid in _BASELINE}
	for mid in overrides:
		if mid not in seen:
			seen[mid] = get_model_info(mid)
	return list(seen.values())


def as_dict(info: ModelInfo) -> dict:
	"""Serialise a :class:`ModelInfo` to a plain dict (for API responses)."""

	return asdict(info)
