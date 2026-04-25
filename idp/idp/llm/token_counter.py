# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Token accounting + budget enforcement.

Cost estimation is purely a function of :class:`TokenUsage` and the
per-model rate card.  Budget enforcement reads daily / monthly limits
from IDP Settings and the user's running total from IDP Conversation
(when present); when the environment is not available it no-ops rather
than raising, so background jobs never blow up mid-task on a misconfigured
site.
"""

from __future__ import annotations

from datetime import datetime

from idp.core.exceptions import LLMBudgetExceededError
from idp.core.logger import get_logger
from idp.idp.llm.model_registry import get_model_info
from idp.idp.llm.providers.base import TokenUsage

logger = get_logger("idp.llm.tokens")


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
	"""Raise :class:`LLMBudgetExceededError` when the caller would exceed budget.

	The daily/monthly limits live on IDP Settings; 0 means unlimited.
	Usage is summed from ``IDP Conversation`` (or any DocType with a
	``total_tokens`` field) when available — otherwise we trust the
	caller and skip enforcement.
	"""

	try:
		import frappe
	except ImportError:
		return

	try:
		daily_cap = int(frappe.db.get_single_value("IDP Settings", "daily_token_budget") or 0)
		monthly_cap = int(frappe.db.get_single_value("IDP Settings", "monthly_token_budget") or 0)
	except Exception as exc:
		logger.debug(f"budget lookup skipped: {exc}")
		return

	if not daily_cap and not monthly_cap:
		return

	today_used = _sum_usage(frappe, user, period="day")
	month_used = _sum_usage(frappe, user, period="month")

	if daily_cap and today_used + estimated_tokens > daily_cap:
		raise LLMBudgetExceededError(
			f"daily token budget exceeded for {user}: {today_used + estimated_tokens} > {daily_cap}",
			details={"user": user, "cap": daily_cap, "used": today_used, "period": "day"},
		)
	if monthly_cap and month_used + estimated_tokens > monthly_cap:
		raise LLMBudgetExceededError(
			f"monthly token budget exceeded for {user}: {month_used + estimated_tokens} > {monthly_cap}",
			details={"user": user, "cap": monthly_cap, "used": month_used, "period": "month"},
		)


def _sum_usage(frappe_module, user: str, *, period: str) -> int:
	"""Sum ``total_tokens`` from ``IDP Conversation`` for *user* over *period*.

	Returns 0 on any DB error or when the DocType / field does not exist.
	"""

	now = datetime.now()
	if period == "day":
		start = now.replace(hour=0, minute=0, second=0, microsecond=0)
	else:  # month
		start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

	try:
		rows = frappe_module.get_all(
			"IDP Conversation",
			filters={"owner": user, "creation": [">=", start]},
			pluck="total_tokens",
		)
	except Exception as exc:
		logger.debug(f"usage sum skipped for {user}/{period}: {exc}")
		return 0

	return sum(int(r or 0) for r in rows)


__all__ = [
	"enforce_budget",
	"estimate_cost",
	"estimate_prompt_tokens",
]
