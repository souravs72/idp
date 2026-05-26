# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Token accounting helpers.

Cost estimation is purely a function of :class:`TokenUsage` and the
per-model rate card.  Token budgets were removed from IDP Settings,
so ``enforce_budget`` is now a no-op kept for import stability.
"""

from __future__ import annotations

from idp.llm.model_registry import get_model_info
from idp.llm.providers.base import TokenUsage


def estimate_cost(usage: TokenUsage, model: str) -> float:
	"""Return the USD cost of *usage* at *model*'s current rate card."""

	info = get_model_info(model)
	return round(
		(usage.prompt / 1_000) * info.input_cost_per_1k
		+ (usage.completion / 1_000) * info.output_cost_per_1k,
		6,
	)


def estimate_prompt_tokens(text: str) -> int:
	"""Rough char/4 heuristic when no SDK tokeniser is available."""

	return max(1, len(text) // 4)


def enforce_budget(user: str, estimated_tokens: int) -> None:
	"""No-op shim: token budgets have been removed from IDP Settings."""

	return None


__all__ = [
	"enforce_budget",
	"estimate_cost",
	"estimate_prompt_tokens",
]
