# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.idp.advanced.prompt_library`.

Fixture-integrity checks on the shipped built-in prompt gallery.
DB-backed seeding / lookup behaviour lives in ``docs/TEST.md``.
"""

from __future__ import annotations


def test_builtin_prompt_gallery_shape(frappe_stub):
	from idp.idp.advanced.prompt_library import _BUILTINS

	assert len(_BUILTINS) >= 5  # Generic + a handful of industries
	for entry in _BUILTINS:
		assert entry["prompt_name"]
		assert entry["industry"]
		assert entry["prompt_body"]
	industries = {e["industry"] for e in _BUILTINS}
	# Generic is required so load_prompt() can always fall back
	assert "Generic" in industries


def test_builtin_prompt_names_are_unique(frappe_stub):
	from idp.idp.advanced.prompt_library import _BUILTINS

	names = [e["prompt_name"] for e in _BUILTINS]
	assert len(names) == len(set(names))
