# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Framework-light tests for :mod:`idp.advanced.feedback`.

Exercises the pure dataclass helpers used to render few-shot prompt
bundles.  Site-backed flows (``record_correction``,
``build_fewshot_bundle`` DB round-trips, ``accuracy_trend`` SQL) live
in ``docs/TEST.md`` as bench console blocks.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# FewShotExample.as_prompt_line
# ---------------------------------------------------------------------------


def test_fewshot_example_prompt_line_basic(frappe_stub):
	from idp.advanced.feedback import FewShotExample

	ex = FewShotExample(
		fieldname="bill_no",
		source_snippet="Bill No: INV-42",
		corrected_value="INV-42",
	)
	line = ex.as_prompt_line()
	assert "bill_no" in line
	assert "INV-42" in line
	# no supplier suffix
	assert "(supplier=" not in line


def test_fewshot_example_prompt_line_with_supplier(frappe_stub):
	from idp.advanced.feedback import FewShotExample

	ex = FewShotExample(
		fieldname="posting_date",
		source_snippet="Date 2026-04-01",
		corrected_value="2026-04-01",
		supplier_or_customer="Acme",
	)
	line = ex.as_prompt_line()
	assert "(supplier=Acme)" in line


def test_fewshot_example_prompt_line_truncates_long_snippet(frappe_stub):
	from idp.advanced.feedback import FewShotExample

	long_snippet = "A " * 400  # 800 chars
	ex = FewShotExample(fieldname="f", source_snippet=long_snippet, corrected_value="v")
	line = ex.as_prompt_line()
	# Body should contain an ellipsis because snippet > 300 chars
	assert "..." in line


# ---------------------------------------------------------------------------
# FewShotBundle.render
# ---------------------------------------------------------------------------


def test_fewshot_bundle_render_empty(frappe_stub):
	from idp.advanced.feedback import FewShotBundle

	bundle = FewShotBundle(target_doctype="Purchase Invoice")
	assert bundle.render() == ""


def test_fewshot_bundle_render_caps_at_max_examples(frappe_stub):
	from idp.advanced.feedback import FewShotBundle, FewShotExample

	bundle = FewShotBundle(
		target_doctype="Purchase Invoice",
		examples=[
			FewShotExample(fieldname=f"f{i}", source_snippet=f"snip {i}", corrected_value=f"v{i}")
			for i in range(10)
		],
	)
	out = bundle.render(max_examples=3)
	# 2 header lines + 3 bullets = 4 newlines between 5 rendered lines
	assert out.count("\n") == 4
	assert "f0" in out and "f2" in out and "f3" not in out
