# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Provider registry + decorator.

Adds a new provider without touching core app code:

.. code-block:: python

    from idp.llm.providers.registry import register_provider
    from idp.llm.providers.base import LLMProvider


    @register_provider("azure")
    class AzureProvider(LLMProvider): ...

Sites can also declare custom providers in ``IDP Settings.custom_providers``
as a JSON list; they are auto-loaded via :func:`get_provider` the first
time the registry is consulted.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

from idp.core.exceptions import LLMProviderUnavailableError
from idp.core.logger import get_logger
from idp.llm.providers.base import LLMProvider

logger = get_logger("idp.llm.registry")

_REGISTRY: dict[str, type[LLMProvider]] = {}
_custom_loaded = False


def register_provider(name: str):
	"""Decorator that registers *cls* under the given provider name.

	Re-registering the same name silently replaces the previous entry so
	tests can monkey-patch providers without tearing down module state.
	"""

	def decorator(cls: type[LLMProvider]) -> type[LLMProvider]:
		if not issubclass(cls, LLMProvider):
			raise TypeError(f"{cls!r} must subclass LLMProvider")
		cls.name = name
		_REGISTRY[name] = cls
		return cls

	return decorator


def get_provider(name: str, **kwargs: Any) -> LLMProvider:
	"""Instantiate the provider registered under *name*.

	Raises :class:`LLMProviderUnavailableError` when the name is unknown
	(after a best-effort attempt to load site-declared custom providers).
	"""

	_ensure_custom_providers_loaded()
	cls = _REGISTRY.get(name)
	if cls is None:
		raise LLMProviderUnavailableError(f"unknown LLM provider: {name!r}; registered: {sorted(_REGISTRY)}")
	return cls(**kwargs)


def list_registered_providers() -> list[str]:
	"""Return the sorted list of currently registered provider names."""

	_ensure_custom_providers_loaded()
	return sorted(_REGISTRY)


def reset_custom_provider_loader_for_tests() -> None:
	"""Test hook that forces :func:`_ensure_custom_providers_loaded` to
	re-run on its next invocation."""

	global _custom_loaded
	_custom_loaded = False


def _ensure_custom_providers_loaded() -> None:
	"""Parse ``IDP Settings.custom_providers`` (JSON list) and importlib each entry.

	Entry shape::

	    [{"name": "azure", "module": "my_app.llm.azure", "class": "AzureProvider"}]

	Errors are logged, not raised — a bad custom provider must not break
	the rest of the app.
	"""

	global _custom_loaded
	if _custom_loaded:
		return
	_custom_loaded = True  # mark first so failures don't cause infinite retries

	try:
		import frappe

		raw = frappe.db.get_single_value("IDP Settings", "custom_providers")
	except Exception as exc:  # site not bootstrapped, table missing, etc.
		logger.debug(f"custom_providers lookup skipped: {exc}")
		return

	if not raw:
		return

	try:
		entries = json.loads(raw)
	except (ValueError, TypeError) as exc:
		logger.warning(f"IDP Settings.custom_providers is not valid JSON: {exc}")
		return

	if not isinstance(entries, list):
		logger.warning("IDP Settings.custom_providers must be a JSON list")
		return

	for entry in entries:
		if not isinstance(entry, dict):
			logger.warning(f"Skipping non-dict custom provider entry: {entry!r}")
			continue
		name = entry.get("name")
		module_path = entry.get("module")
		class_name = entry.get("class")
		if not (name and module_path and class_name):
			logger.warning(f"Skipping incomplete custom provider entry: {entry!r}")
			continue
		try:
			module = importlib.import_module(module_path)
			cls = getattr(module, class_name)
		except Exception as exc:
			logger.warning(f"Cannot load custom provider {entry!r}: {exc}")
			continue
		if not isinstance(cls, type) or not issubclass(cls, LLMProvider):
			logger.warning(f"Custom provider {class_name} does not subclass LLMProvider")
			continue
		cls.name = name
		_REGISTRY[name] = cls
		logger.info(f"Registered custom LLM provider: {name}")
