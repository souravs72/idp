# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Dataclass-level tests for :mod:`idp.validators.schema_validator`.

Full DocType validation requires a Frappe site, so here we restrict
ourselves to the dataclass contracts and their defaults.  End-to-end
schema validation is covered in ``docs/TEST.md`` bench console blocks.
"""

from __future__ import annotations


def test_validation_issue_defaults(frappe_stub):  # noqa: ARG001
	from idp.validators.schema_validator import ValidationIssue

	issue = ValidationIssue(field="supplier", message="missing")
	assert issue.severity == "error"
	assert issue.value is None


def test_validation_result_defaults(frappe_stub):  # noqa: ARG001
	from idp.validators.schema_validator import ValidationResult

	result = ValidationResult()
	assert result.is_valid is True
	assert result.errors == []
	assert result.warnings == []
	assert result.resolved_links == {}
	assert result.missing_masters == []


def test_validation_result_flags_errors(frappe_stub):  # noqa: ARG001
	from idp.validators.schema_validator import ValidationIssue, ValidationResult

	result = ValidationResult()
	result.errors.append(ValidationIssue(field="date", message="invalid"))
	result.is_valid = False
	assert result.is_valid is False
	assert len(result.errors) == 1
	assert result.errors[0].field == "date"
