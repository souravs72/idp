# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Process-wide tool registry and dispatcher (Phase 19).

The registry is populated at import time by the side-effect imports in
:mod:`idp.idp.llm.tools.__init__` so callers can simply do::

    from idp.idp.llm.tools.registry import (
        get_provider_schemas,
        dispatch,
        load_tool_registry,
    )

    schemas = get_provider_schemas()
    result = dispatch("extract_document", {"file_id": "file_1"}, ctx)

We do not register tools at module-level inside the agent loop — that
would force a circular import.  Instead the agent calls
:func:`load_tool_registry` once which imports the tool modules and
returns the snapshot.
"""

from __future__ import annotations

from typing import Any

from idp.core.logger import get_logger
from idp.idp.llm.tools.base import ToolContext, ToolResult, ToolSpec

logger = get_logger("idp.llm.tools.registry")


_REGISTRY: dict[str, ToolSpec] = {}
_LOADED = False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_tool(spec: ToolSpec) -> None:
	"""Register *spec* in the global registry.

	Re-registering the same name is allowed and overwrites the
	previous entry — useful for hot-reload during ``bench --site
	test.local console`` development.
	"""

	if not spec.name:
		raise ValueError("ToolSpec.name is required")
	if spec.name in _REGISTRY:
		logger.debug(f"tool registry: replacing existing tool {spec.name!r}")
	_REGISTRY[spec.name] = spec


def load_tool_registry() -> dict[str, ToolSpec]:
	"""Trigger side-effect imports for built-in tools and return the snapshot.

	Importing :mod:`idp.idp.llm.tools` runs each tool module's
	``@tool`` decorator which populates ``_REGISTRY``.
	"""

	global _LOADED
	if not _LOADED:
		import idp.idp.llm.tools as _tools_pkg

		_LOADED = True
	return dict(_REGISTRY)


def reset_registry() -> None:
	"""Test-only: clear the registry and the loaded flag."""

	global _LOADED
	_REGISTRY.clear()
	_LOADED = False


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get_tool(name: str) -> ToolSpec | None:
	load_tool_registry()
	return _REGISTRY.get(name)


def list_tools() -> list[ToolSpec]:
	load_tool_registry()
	return list(_REGISTRY.values())


def get_provider_schemas(
	*,
	names: list[str] | None = None,
	user: str | None = None,
) -> list[dict]:
	"""Return the OpenAI-style tool schema list to ship to the LLM.

	If *names* is provided, only those tools are included (preserving
	registration order otherwise).

	When *user* is supplied (Phase 26 §26.2), tools the user is not
	permitted to invoke (via ``IDP Tool Configuration``) are filtered
	out so the LLM never even sees them in ``tools/list``.
	"""

	load_tool_registry()
	specs = (
		[s for s in _REGISTRY.values() if s.name in set(names)]
		if names is not None
		else list(_REGISTRY.values())
	)
	if user is not None:
		from idp.idp.llm.tools.access import check_tool_access

		specs = [
			s
			for s in specs
			if check_tool_access(s.name, user, requires_role=s.requires_role).allowed
		]
	return [s.to_provider_schema() for s in specs]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch(name: str, arguments: dict | None, ctx: ToolContext) -> ToolResult:
	"""Execute the tool registered under *name*.

	Translates exceptions and unknown tools into stop-on-error
	envelopes — the agent loop never has to wrap dispatcher calls in
	its own try/except.
	"""

	load_tool_registry()
	spec = _REGISTRY.get(name)
	if spec is None:
		logger.warning(f"unknown tool requested by LLM: {name!r}")
		return ToolResult.fail(
			f"unknown tool: {name!r}",
			error_code="UNKNOWN_TOOL",
			stop_processing=True,
		)

	# Role gate — Phase 26 §26.2 layers ``IDP Tool Configuration`` on
	# top of the in-code ``ToolSpec.requires_role`` default.  When
	# Frappe is unavailable (pure unit tests) the access check falls
	# back to allowing the call.
	try:
		from idp.idp.llm.tools.access import check_tool_access

		decision = check_tool_access(name, ctx.user, requires_role=spec.requires_role)
		if not decision.allowed:
			return ToolResult.fail(
				decision.reason or f"caller is not authorised to invoke {name!r}",
				error_code="PERMISSION_DENIED",
				stop_processing=True,
			)
	except Exception:
		# Fall back to legacy in-code check if the access layer blows
		# up (defensive — never block dispatch on a cache bug).
		if spec.requires_role and not _user_has_role(ctx.user, spec.requires_role):
			return ToolResult.fail(
				f"caller is not authorised to invoke {name!r}",
				error_code="PERMISSION_DENIED",
				stop_processing=True,
			)

	args = arguments or {}
	try:
		result = spec.handler(args, ctx)
	except Exception as exc:
		return _translate_exception(name, exc)

	# Allow handlers to return a plain dict for ergonomics.
	if isinstance(result, dict):
		return ToolResult(
			success=bool(result.get("success", True)),
			data=result.get("data"),
			error=result.get("error"),
			error_code=result.get("error_code"),
			stop_processing=bool(result.get("stop_processing", False)),
			card=result.get("card"),
		)
	if not isinstance(result, ToolResult):
		return ToolResult.fail(
			f"tool {name!r} returned unsupported type {type(result).__name__}",
			error_code="BAD_TOOL_RESULT",
			stop_processing=True,
		)
	return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_has_role(user: str, role: str) -> bool:
	try:
		import frappe
	except ImportError:
		return True
	try:
		roles = set(frappe.get_roles(user))
	except Exception:
		return False
	# Administrator always passes.
	return role in roles or "Administrator" == user or "System Manager" in roles


def _translate_exception(tool_name: str, exc: Exception) -> ToolResult:
	"""Translate a raised exception into a ToolResult envelope.

	Stop-on-error error codes follow §19.3 of the roadmap.
	"""

	# Local imports to avoid touching frappe in pure tests.
	from idp.core.exceptions import (
		ExtractionError,
		FileAliasNotFoundError,
		FileTooLargeError,
		IDPError,
		LLMBudgetExceededError,
		MissingMasterError,
		OCRError,
		RateLimitExceededError,
		SecurityError,
		UnsupportedFormatError,
		ValidationError,
	)

	stop = True
	code = "TOOL_ERROR"
	if isinstance(exc, FileAliasNotFoundError):
		code = "FILE_ALIAS_NOT_FOUND"
	elif isinstance(exc, FileTooLargeError):
		code = "FILE_TOO_LARGE"
	elif isinstance(exc, UnsupportedFormatError):
		code = "UNSUPPORTED_FORMAT"
	elif isinstance(exc, OCRError):
		code = "OCR_FAILED"
	elif isinstance(exc, ExtractionError):
		code = "EXTRACTION_FAILED"
	elif isinstance(exc, SecurityError):
		code = "PERMISSION_DENIED"
	elif isinstance(exc, RateLimitExceededError):
		code = "RATE_LIMITED"
	elif isinstance(exc, LLMBudgetExceededError):
		code = "BUDGET_EXCEEDED"
	elif isinstance(exc, MissingMasterError):
		code = "MISSING_MASTER"
		stop = False  # LLM can recover via create_master
	elif isinstance(exc, ValidationError):
		code = "VALIDATION_FAILED"
		stop = False  # LLM can fix and retry
	elif isinstance(exc, IDPError):
		code = "IDP_ERROR"
	else:
		# Unexpected — log and stop.
		logger.exception(f"tool {tool_name!r} raised unexpected error")
		code = "UNEXPECTED_ERROR"

	details: dict[str, Any] = getattr(exc, "details", {}) or {}
	if "stop_processing" in details:
		stop = bool(details["stop_processing"])

	return ToolResult.fail(
		str(exc) or exc.__class__.__name__,
		error_code=code,
		stop_processing=stop,
	)


def get_cached_provider_schemas(
	*,
	names: list[str] | None = None,
	user: str | None = None,
) -> list[dict]:
	"""TTL-cached variant of :func:`get_provider_schemas` (Phase 26 §26.3).

	Caches by ``(enabled_plugin_set, enabled_tool_set, role_set,
	name_filter)``.  Falls back to :func:`get_provider_schemas` on
	cache miss or when Frappe is unavailable.
	"""

	# Resolve current context.
	try:
		from idp.plugins.loader import enabled_plugins as _enabled_plugins
	except Exception:
		_enabled_plugins = None  # type: ignore[assignment]
	try:
		from idp.idp.llm.tools.registry_cache import (
			get_cached_schemas,
			set_cached_schemas,
		)
	except Exception:
		return get_provider_schemas(names=names, user=user)

	enabled_plugin_names: list[str] = []
	if _enabled_plugins is not None:
		try:
			enabled_plugin_names = [p.name for p in _enabled_plugins()]
		except Exception:
			enabled_plugin_names = []

	# Enabled tool set = current registry contents.
	load_tool_registry()
	enabled_tool_names = sorted(_REGISTRY.keys())

	user_roles: list[str] = []
	if user:
		try:
			import frappe

			user_roles = list(frappe.get_roles(user))
		except Exception:
			user_roles = []

	cached = get_cached_schemas(
		enabled_plugins=enabled_plugin_names,
		enabled_tools=enabled_tool_names,
		user_roles=user_roles,
		name_filter=names,
	)
	if cached is not None:
		return cached

	fresh = get_provider_schemas(names=names, user=user)
	set_cached_schemas(
		fresh,
		enabled_plugins=enabled_plugin_names,
		enabled_tools=enabled_tool_names,
		user_roles=user_roles,
		name_filter=names,
	)
	return fresh


__all__ = [
	"dispatch",
	"get_cached_provider_schemas",
	"get_provider_schemas",
	"get_tool",
	"list_tools",
	"load_tool_registry",
	"register_tool",
	"reset_registry",
]
