# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""``update_document`` — modify an existing ERPNext record in place.

Two-step pattern, mirroring ``propose_create_document`` → ``create_document``:

* ``dry_run=True`` (default) builds a field-by-field before→after
  diff and surfaces it as an ``UpdateCard`` for the user.  Nothing
  is mutated.
* ``dry_run=False`` re-runs the same diff and applies it via
  ``doc.update(updates) + doc.save()``.  The audit trail captures the
  diff and (optionally) the user-supplied reason.

The tool is gated by ``frappe.has_permission(doctype, "write")`` and
refuses to touch submitted submittable docs unless the targeted field
is marked ``allow_on_submit``.
"""

from __future__ import annotations

from typing import Any

from idp.tools.base import ToolContext, ToolResult, publish_progress, tool

_RATE_LIMIT_PER_HOUR = 20


_PARAMETERS_SCHEMA = {
	"type": "object",
	"properties": {
		"doctype": {"type": "string", "description": "ERPNext DocType."},
		"name": {"type": "string", "description": "Primary key of the record to update."},
		"updates": {
			"type": "object",
			"description": "Field name → new value map.",
			"additionalProperties": True,
		},
		"dry_run": {
			"type": "boolean",
			"description": (
				"When true (default), build the diff and render an UpdateCard but "
				"do not save.  When false, apply the updates and audit-log them."
			),
		},
		"auto_resolve_links": {
			"type": "boolean",
			"description": (
				"When true (default), Link-field values that don't match a canonical "
				"name are resolved against {doctype}_name / title_field / name LIKE "
				"before the diff is built.  Set to false to require canonical names "
				"verbatim."
			),
		},
		"reason": {
			"type": "string",
			"description": "Optional free-text reason recorded on the audit row.",
		},
	},
	"required": ["doctype", "name", "updates"],
	"additionalProperties": False,
}


@tool(
	name="update_document",
	description=(
		"Modify fields on an existing ERPNext record.  YOU MUST CALL THIS "
		"TOOL for every user request to update a record — never paraphrase "
		"the proposed change as a markdown 'Field | Before | After' table "
		"in your assistant reply.  Even if a similar update was proposed "
		"or attempted earlier in the conversation, treat each new user "
		"message as a fresh request and call this tool again.  Call "
		"directly with the human-readable value the user supplied — DO "
		"NOT call search_documents first just to look up the canonical "
		"name.  Link fields are auto-resolved server-side: e.g. "
		"cost_center='Test' resolves to 'Test - TTD' scoped to the parent "
		"doc's company, and group rows on tree doctypes (Cost Center, "
		"Account, …) are skipped automatically.  Updates cascade into "
		"child tables when the same fieldname exists on both header and "
		"items.  Defaults to dry_run=true and renders an UpdateCard for "
		"the user to confirm in the UI — do NOT also write a prose "
		"summary of the diff; the card is the response.  Refuses to "
		"modify locked fields on submitted submittable documents.  If "
		"the tool returns AMBIGUOUS_LINK or LINK_NOT_FOUND, recover by "
		"calling search_documents on the target doctype using the "
		"company reported in the error envelope."
	),
	parameters_schema=_PARAMETERS_SCHEMA,
	requires_role="System Manager",
	mutating=True,
)
def update_document(arguments: dict, ctx: ToolContext) -> ToolResult:
	args = arguments or {}
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	updates = args.get("updates") or {}
	dry_run = bool(args.get("dry_run", True))
	auto_resolve_links = bool(args.get("auto_resolve_links", True))
	reason = (args.get("reason") or "").strip() or None

	if not doctype:
		return ToolResult.fail(
			"doctype is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not name:
		return ToolResult.fail(
			"name is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)
	if not isinstance(updates, dict) or not updates:
		return ToolResult.fail(
			"updates object with at least one field is required",
			error_code="MISSING_ARGUMENT",
			stop_processing=False,
		)

	try:
		import frappe
	except ImportError:
		return ToolResult.fail(
			"frappe runtime not available",
			error_code="UNEXPECTED_ERROR",
			stop_processing=True,
		)

	# Apply per-tool rate limit only when actually mutating — dry runs
	# are read-equivalent and shouldn't burn the user's write budget.
	if not dry_run:
		try:
			from idp.core.rate_limit import check_and_consume_tool

			check_and_consume_tool(
				"update_document",
				user=ctx.user,
				limit_per_hour=_RATE_LIMIT_PER_HOUR,
			)
		except Exception as exc:
			if exc.__class__.__name__ == "RateLimitExceededError":
				return ToolResult.fail(
					str(exc),
					error_code="RATE_LIMITED",
					stop_processing=True,
				)

	try:
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:  # type: ignore[attr-defined]
		return ToolResult.fail(
			f"{doctype} {name!r} not found",
			error_code="RECORD_NOT_FOUND",
			stop_processing=False,
		)
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	if not frappe.has_permission(doctype, "write", doc=doc, user=ctx.user):
		return ToolResult.fail(
			f"write permission denied on {doctype} {name!r}",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)

	# Header-vs-child classification.  Doctypes like Sales Invoice expose
	# the same fieldname (``cost_center``) on the header AND on each
	# child row of an items table — a single-tool call should update
	# both, otherwise the user has to remember the second tool call.
	header_updates, child_updates, child_doctypes = _split_updates(doc, updates)

	is_submitted = int(getattr(doc, "docstatus", 0) or 0) == 1
	locked = (
		_locked_fields_on_submit(doctype, header_updates.keys()) if is_submitted else []
	)
	if locked:
		return ToolResult.fail(
			(
				f"{doctype} {name!r} is submitted; cannot modify locked field(s): "
				+ ", ".join(sorted(locked))
			),
			error_code="DOC_LOCKED",
			stop_processing=False,
		)

	# Auto-resolve Link-field values that don't match a canonical name.
	# Common case: the LLM (or user) sends "Test" for a Cost Center
	# whose actual name is "Test - TTD" because of the autoname
	# convention.  We resolve it server-side and surface the
	# resolution on the card so the user sees what we matched against.
	#
	# Multi-company scoping: if the parent doc carries a ``company`` and
	# the Link target also has a ``company`` field, we narrow the search
	# by company so a ``Test`` cost center in Company A is not surfaced
	# as ambiguous against ``Test`` in Company B.  Falls back to the
	# request-level company hint when the parent doesn't expose one.
	parent_company = None
	if hasattr(doc, "get"):
		parent_company = doc.get("company")
	if not parent_company:
		parent_company = getattr(ctx, "company", None)

	resolutions: list[dict] = []
	if auto_resolve_links:
		header_updates, header_res, ambiguous, missing = _resolve_links(
			doctype, header_updates, company=parent_company,
		)
		resolutions.extend(header_res)
		for child_fieldname, cols in list(child_updates.items()):
			child_dt = child_doctypes.get(child_fieldname)
			if not child_dt:
				continue
			resolved_cols, child_res, c_ambig, c_miss = _resolve_links(
				child_dt, cols, company=parent_company,
			)
			child_updates[child_fieldname] = resolved_cols
			for r in child_res:
				r["scope"] = "child"
				r["child_table"] = child_fieldname
				resolutions.append(r)
			ambiguous.extend(c_ambig)
			missing.extend(c_miss)
		if ambiguous:
			return ToolResult.fail(
				_describe_ambiguity(ambiguous),
				error_code="AMBIGUOUS_LINK",
				stop_processing=False,
			)
		if missing:
			return ToolResult.fail(
				_describe_missing(missing),
				error_code="LINK_NOT_FOUND",
				stop_processing=False,
			)

	diff = _build_diff(doc, header_updates, child_updates, resolutions=resolutions)

	# Pre-flight warnings — catch the most common ERPNext apply-time
	# guards (Repost Accounting Ledger Settings, …) BEFORE the user
	# clicks Confirm Update, so they don't get the surprise apply
	# failure that happens after a savepoint-rolled-back doc.save().
	warnings = _collect_preflight_warnings(doctype, doc, header_updates, child_updates)

	if dry_run:
		card = _build_card(doctype, name, diff, reason=reason, warnings=warnings)
		# Terminal turn: the UpdateCard is itself the user-facing
		# response.  Stopping the agent loop here prevents the LLM from
		# emitting a redundant prose summary of the same diff (which was
		# showing up as a duplicate card below the rendered UpdateCard).
		return ToolResult(
			success=True,
			data={
				"doctype": doctype,
				"name": name,
				"diff": diff,
				"dry_run": True,
				"changed_count": sum(1 for d in diff if d["changed"]),
				"warnings": warnings,
			},
			card=card,
			stop_processing=True,
		)

	publish_progress(
		ctx,
		tool_name="update_document",
		user_visible_message=f"Updating {doctype} {name}…",
		stage="update_start",
	)

	# Wrap the mutation in a savepoint.  Submitted doctypes use
	# ``db_update`` under ``doc.save()`` which commits ``allow_on_submit``
	# field changes directly — if ``on_update_after_submit`` then raises
	# (e.g. ERPNext's "not allowed to be reposted" guard on Sales
	# Invoice), the field is already persisted while the caller sees a
	# failure envelope.  Savepoint + explicit rollback closes that gap.
	savepoint_name = "idp_update_document"
	savepoint_active = False
	try:
		frappe.db.savepoint(savepoint_name)
		savepoint_active = True
	except Exception:
		# Older / non-MariaDB backends without savepoint support; fall
		# back to a flat save and live with the partial-commit risk.
		savepoint_active = False

	try:
		if header_updates:
			doc.update(header_updates)
		for child_fieldname, columns in child_updates.items():
			for row in doc.get(child_fieldname) or []:
				for col, value in columns.items():
					row.set(col, value)
		doc.save()
	except frappe.PermissionError as exc:  # type: ignore[attr-defined]
		_rollback_savepoint(frappe, savepoint_name, savepoint_active)
		return ToolResult.fail(
			str(exc) or "permission denied",
			error_code="PERMISSION_DENIED",
			stop_processing=True,
		)
	except Exception as exc:
		_rollback_savepoint(frappe, savepoint_name, savepoint_active)
		return ToolResult.fail(
			str(exc) or exc.__class__.__name__,
			error_code="UPDATE_FAILED",
			stop_processing=True,
		)
	else:
		# Release the savepoint on success so it doesn't accumulate in
		# the connection's savepoint stack across multiple updates in
		# the same request.
		if savepoint_active:
			try:
				frappe.db.sql(f"RELEASE SAVEPOINT {savepoint_name}")
			except Exception:
				pass

	# Audit log — best-effort; never breaks the tool.
	try:
		from idp.core.audit import log_doc_update

		log_doc_update(
			doctype=doctype,
			name=name,
			diff=diff,
			user=ctx.user,
			reason=reason,
			company=ctx.company,
			success=True,
		)
	except Exception:
		pass

	changed_count = sum(1 for d in diff if d["changed"])
	body = (
		f"{doctype} {name} updated ({changed_count} field"
		+ ("s" if changed_count != 1 else "")
		+ " changed)."
	)
	return ToolResult(
		success=True,
		data={
			"doctype": doctype,
			"name": name,
			"diff": diff,
			"dry_run": False,
			"changed_count": changed_count,
		},
		card={
			"card_type": "InfoCard",
			"title": f"{doctype} updated",
			"body": body,
			"link": {"doctype": doctype, "name": name},
		},
		stop_processing=True,
	)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rollback_savepoint(frappe_mod: Any, name: str, active: bool) -> None:
	"""Roll back to *name* if we successfully created it earlier.

	Wraps the call in its own try/except so a rollback failure never
	masks the original update error the caller is about to surface.
	"""
	if not active:
		return
	try:
		frappe_mod.db.rollback(save_point=name)
	except Exception:
		# As a last resort, fall through — the caller still returns a
		# failure envelope, and the next request boundary will flush any
		# uncommitted state.
		pass


def _split_updates(
	doc: Any, updates: dict
) -> tuple[dict, dict[str, dict], dict[str, str]]:
	"""Partition *updates* into header-level and child-table updates.

	Returns ``(header_updates, child_updates, child_doctypes)``:

	* ``child_updates``    — ``{child_table_fieldname: {col: value, ...}}``
	* ``child_doctypes``   — ``{child_table_fieldname: child_doctype}``
	  used downstream by the Link auto-resolver so it can introspect
	  the right meta for each cascaded column.

	When the same key exists on both the header *and* one or more child
	tables (Sales Invoice ``cost_center`` being the canonical case), the
	update is applied to both — header via the standard map, and each
	child row via the child-update map.
	"""
	try:
		import frappe

		header_meta = frappe.get_meta(doc.doctype)
	except Exception:
		return dict(updates), {}, {}

	header_fields = {df.fieldname for df in (header_meta.fields or [])}
	table_fields = [
		df for df in (header_meta.fields or [])
		if getattr(df, "fieldtype", None) in {"Table", "Table MultiSelect"}
	]
	child_doctypes: dict[str, str] = {}
	child_index: dict[str, list[str]] = {}
	for tbl in table_fields:
		try:
			child_meta = frappe.get_meta(tbl.options)
		except Exception:
			continue
		child_doctypes[tbl.fieldname] = tbl.options
		for cdf in child_meta.fields or []:
			child_index.setdefault(cdf.fieldname, []).append(tbl.fieldname)

	header_updates: dict[str, Any] = {}
	child_updates: dict[str, dict[str, Any]] = {}
	for key, value in updates.items():
		if key in header_fields:
			header_updates[key] = value
		for tbl_fieldname in child_index.get(key, []):
			child_updates.setdefault(tbl_fieldname, {})[key] = value
	return header_updates, child_updates, child_doctypes


# ---------------------------------------------------------------------------
# Link auto-resolution
# ---------------------------------------------------------------------------


def _resolve_links(
	doctype: str, updates: dict, *, company: str | None = None,
) -> tuple[dict, list[dict], list[dict], list[dict]]:
	"""Resolve Link-field values that don't match a canonical name.

	Returns a 4-tuple:

	* ``resolved_updates``    — same map, with Link values swapped to canonical names.
	* ``resolutions``         — ``[{fieldname, target, supplied, resolved}]`` — informational.
	* ``ambiguities``         — ``[{fieldname, target, supplied, candidates}]`` — caller bails.
	* ``misses``              — ``[{fieldname, target, supplied}]`` — caller bails.

	Resolution order for each Link value:

	1. Exact ``name`` match → unchanged.
	2. ``{snake_doctype}_name`` field == value (e.g. ``cost_center_name``).
	3. ``meta.title_field`` == value.
	4. ``name LIKE 'value%'`` prefix scan.

	The first step that returns exactly one match wins.  Anything else
	(zero / multiple) flows into ``ambiguities`` or ``misses`` so the
	tool returns a recoverable error envelope rather than silently
	guessing.

	*company* — when set, ``Test`` in Company A is not surfaced as
	ambiguous against ``Test`` in Company B.  Only applied when the
	target meta exposes a ``company`` field.
	"""

	try:
		import frappe

		meta = frappe.get_meta(doctype)
	except Exception:
		return dict(updates), [], [], []

	resolved_updates: dict = {}
	resolutions: list[dict] = []
	ambiguities: list[dict] = []
	misses: list[dict] = []

	for fieldname, value in updates.items():
		df = meta.get_field(fieldname) if hasattr(meta, "get_field") else None
		fieldtype = getattr(df, "fieldtype", None) if df else None
		target = getattr(df, "options", None) if df else None
		if (
			df is None
			or fieldtype != "Link"
			or not target
			or not isinstance(value, str)
			or not value.strip()
		):
			resolved_updates[fieldname] = value
			continue

		stripped = value.strip()
		# Step 1: exact name match — fast path.
		try:
			if frappe.db.exists(target, stripped):
				resolved_updates[fieldname] = stripped
				continue
		except Exception:
			# DB unreachable; pass the value through unchanged and let
			# the save() path surface the error.
			resolved_updates[fieldname] = value
			continue

		matches = _find_link_matches(target, stripped, company=company)
		# Capture the company hint on each ambiguity/miss so the error
		# message tells the LLM (and the user) which company we scoped
		# to — avoids the "Test - TTD belongs to Company X, not Y"
		# guessing that the LLM otherwise has to fall back on.
		if len(matches) == 1:
			canonical = matches[0]
			resolved_updates[fieldname] = canonical
			resolutions.append(
				{
					"fieldname": fieldname,
					"target": target,
					"supplied": value,
					"resolved": canonical,
					"company_scope": company,
				}
			)
		elif len(matches) > 1:
			ambiguities.append(
				{
					"fieldname": fieldname,
					"target": target,
					"supplied": value,
					"candidates": matches[:10],
					"company_scope": company,
				}
			)
			resolved_updates[fieldname] = value
		else:
			misses.append(
				{
					"fieldname": fieldname,
					"target": target,
					"supplied": value,
					"company_scope": company,
				}
			)
			resolved_updates[fieldname] = value

	return resolved_updates, resolutions, ambiguities, misses


def _find_link_matches(
	target: str, value: str, *, company: str | None = None,
) -> list[str]:
	"""Return the deduped set of candidate ``name`` values for *target*.

	Probes (in this order — each step only runs when the prior steps
	returned nothing):

	1. ``{snake_doctype}_name`` field equality
	2. ``meta.title_field`` equality
	3. ``name LIKE 'value%'`` prefix

	When *company* is supplied AND the target doctype exposes a
	``company`` field, every query is narrowed by that company.  If the
	narrowed query returns nothing the same probe is retried without
	the company filter (so non-company-scoped doctypes still resolve);
	if it returns a candidate the unscoped pass is skipped to avoid
	collapsing two companies' identically-named records into ambiguity.
	"""
	try:
		import frappe

		meta = frappe.get_meta(target)
	except Exception:
		return []

	has_company_field = (
		hasattr(meta, "get_field") and meta.get_field("company") is not None
	)
	effective_company = company if (company and has_company_field) else None

	# Tree doctypes — never resolve to a group row.  Cost Center,
	# Account, Department, Warehouse and friends all carry the
	# ``is_group`` flag; transactional updates always target a leaf.
	is_tree_doctype = (
		hasattr(meta, "get_field") and meta.get_field("is_group") is not None
	)

	def _query(filters: dict) -> list[str]:
		# Run scoped first (if applicable), then fall back to unscoped
		# only when the scoped probe returned nothing.
		base = dict(filters)
		if is_tree_doctype:
			base["is_group"] = 0
		passes: list[dict] = []
		if effective_company:
			passes.append({**base, "company": effective_company})
		passes.append(base)
		for pass_filters in passes:
			try:
				rows = frappe.get_all(
					target,
					filters=pass_filters,
					fields=["name"],
					limit_page_length=10,
				)
			except Exception:
				continue
			names = [r["name"] for r in rows if r.get("name")]
			if names:
				return names
		return []

	matches: list[str] = []
	snake = target.lower().replace(" ", "_")
	for candidate_field in (f"{snake}_name", getattr(meta, "title_field", None)):
		if not candidate_field or candidate_field == "name":
			continue
		if not (
			hasattr(meta, "get_field") and meta.get_field(candidate_field) is not None
		):
			continue
		matches = _query({candidate_field: value})
		if matches:
			break

	if not matches:
		matches = _query({"name": ["like", f"{value}%"]})

	# De-dupe while preserving order.
	seen: set[str] = set()
	unique = []
	for m in matches:
		if m in seen:
			continue
		seen.add(m)
		unique.append(m)
	return unique


def _describe_ambiguity(items: list[dict]) -> str:
	parts = []
	for it in items:
		fns = it["fieldname"]
		supplied = it["supplied"]
		cands = ", ".join(it["candidates"])
		scope = (
			f" (scoped to company {it['company_scope']!r})"
			if it.get("company_scope")
			else ""
		)
		parts.append(
			f"{fns}: {supplied!r} matched multiple {it['target']} records{scope}: {cands}"
		)
	return "Ambiguous link value(s); call again with the canonical name. " + " | ".join(
		parts
	)


def _describe_missing(items: list[dict]) -> str:
	parts = []
	for it in items:
		scope = (
			f" within company {it['company_scope']!r}"
			if it.get("company_scope")
			else ""
		)
		parts.append(
			f"{it['fieldname']}: no {it['target']} matches {it['supplied']!r}{scope}"
		)
	return (
		"Could not resolve link value(s); use search_documents to find the canonical "
		"name first. " + " | ".join(parts)
	)


def _build_diff(
	doc: Any,
	header_updates: dict,
	child_updates: dict[str, dict],
	*,
	resolutions: list[dict] | None = None,
) -> list[dict]:
	# Index resolutions by (scope, child_table, fieldname) so we can
	# attach "supplied → resolved" hints to the diff rows the UI renders.
	resolution_index: dict[tuple[str, str | None, str], dict] = {}
	for r in resolutions or []:
		key = (
			r.get("scope", "header"),
			r.get("child_table"),
			r.get("fieldname"),
		)
		resolution_index[key] = r

	rows: list[dict] = []
	for fieldname, after in header_updates.items():
		before = doc.get(fieldname) if hasattr(doc, "get") else None
		row = {
			"fieldname": fieldname,
			"before": before,
			"after": after,
			"changed": _normalise(before) != _normalise(after),
			"scope": "header",
		}
		hit = resolution_index.get(("header", None, fieldname))
		if hit:
			row["resolved_from"] = hit["supplied"]
		rows.append(row)
	for tbl_fieldname, cols in child_updates.items():
		table_rows = doc.get(tbl_fieldname) or []
		# Empty child tables can't be "cascaded into" — surfacing a row
		# like ``taxes.cost_center: [] → Test - TTD`` is noise that
		# confuses the user (and gets applied to zero rows anyway).
		if not table_rows:
			continue
		for col, after in cols.items():
			# Surface a single diff row per child column with the set of
			# distinct before-values so the UpdateCard stays compact even
			# when the table has many rows.
			before_values = sorted(
				{
					(r.get(col) if hasattr(r, "get") else None)
					for r in table_rows
				},
				key=lambda v: (v is None, str(v)),
			)
			before_repr = (
				before_values[0] if len(before_values) == 1 else before_values
			)
			row = {
				"fieldname": f"{tbl_fieldname}.{col}",
				"before": before_repr,
				"after": after,
				"changed": any(
					_normalise(r.get(col) if hasattr(r, "get") else None)
					!= _normalise(after)
					for r in table_rows
				),
				"scope": "child",
				"child_table": tbl_fieldname,
				"row_count": len(table_rows),
			}
			hit = resolution_index.get(("child", tbl_fieldname, col))
			if hit:
				row["resolved_from"] = hit["supplied"]
			rows.append(row)
	return rows


def _build_card(
	doctype: str,
	name: str,
	diff: list[dict],
	*,
	reason: str | None,
	warnings: list[str] | None = None,
) -> dict:
	changed = [d for d in diff if d["changed"]]
	summary = (
		f"Update {doctype} {name}: {len(changed)} field"
		+ ("s" if len(changed) != 1 else "")
		+ " will change."
	)
	if not changed:
		summary = f"No changes — every supplied field on {doctype} {name} already matches."
	return {
		"card_type": "UpdateCard",
		"doctype": doctype,
		"name": name,
		"diff": diff,
		"reason": reason,
		"summary": summary,
		"warnings": list(warnings or []),
	}


# ---------------------------------------------------------------------------
# Pre-flight warnings
# ---------------------------------------------------------------------------


# Known controller methods that indicate a doctype emits GL entries —
# i.e. ERPNext's repost-ledger guard can fire when the doc is mutated
# post-submit.  Detection is via ``hasattr`` on the loaded doc class,
# so the check naturally extends to custom apps that follow the same
# pattern and to future ERPNext additions without code changes here.
#
# We avoid hardcoding doctype names because:
#  * ERPNext periodically adds new accounting doctypes (or renames),
#  * Custom apps register their own submittable accounting docs,
#  * Even within a "guarded" doctype, only some field changes route
#    through the GL — we can't statically prove that, so the warning
#    is phrased as "may fail" rather than "will fail" to avoid the
#    false-alarm problem on benign edits (e.g. updating ``remarks``).
_GL_HOOK_METHODS = (
	"make_gl_entries",
	"make_gl_entries_for_reposting",
	"repost_accounting_entries",
	"validate_accounting_period",
)


def _collect_preflight_warnings(
	doctype: str,
	doc: Any,
	header_updates: dict,
	child_updates: dict[str, dict],
) -> list[str]:
	"""Return user-facing warnings to render on the UpdateCard.

	Each warning describes a foreseeable apply-time guard that the
	user can resolve in ERPNext before clicking Confirm Update.
	Best-effort: any introspection failure degrades to "no warning"
	rather than raising — we don't want pre-flight to break the
	dry-run path.
	"""
	warnings: list[str] = []
	is_submitted = int(getattr(doc, "docstatus", 0) or 0) == 1
	if is_submitted:
		w = _check_repost_ledger_guard(doctype, doc, header_updates, child_updates)
		if w:
			warnings.append(w)
	return warnings


def _doctype_emits_gl_entries(doc: Any) -> bool:
	"""Detect whether the doctype's controller produces GL entries.

	A submittable doc whose class defines any of the known GL hook
	methods (``make_gl_entries`` & co) routes through ERPNext's
	post-submit accounting validation — which is exactly where the
	repost-ledger guard lives.  Custom doctypes that follow the same
	convention are picked up automatically.
	"""
	try:
		cls = doc.__class__
	except Exception:
		return False
	for method in _GL_HOOK_METHODS:
		if hasattr(cls, method):
			return True
	return False


def _check_repost_ledger_guard(
	doctype: str,
	doc: Any,
	header_updates: dict,
	child_updates: dict[str, dict],
) -> str | None:
	"""Surface ERPNext's repost-ledger guard at dry-run time.

	When the target doctype's controller emits GL entries AND the doc
	is submitted, ERPNext's ``on_update_after_submit`` can raise
	``"<DocType> is not allowed to be reposted. Modify Repost
	Accounting Ledger Settings to enable reposting."`` unless that
	doctype is listed under ``Repost Accounting Ledger Settings``.

	Returns the warning string when the guard would likely fire, else
	``None``.  The check is conservative — phrased as "may" because not
	every field change on a GL-emitting doctype routes through the
	repost path (e.g. ``remarks`` doesn't), but the user is best
	positioned to decide whether their specific edit needs the setting.
	"""
	if not header_updates and not child_updates:
		return None
	if not _doctype_emits_gl_entries(doc):
		# Doctype doesn't produce GL entries — the repost guard won't
		# fire regardless of what's in Repost Accounting Ledger Settings.
		return None
	try:
		import frappe

		if not frappe.db.exists("DocType", "Repost Accounting Ledger Settings"):
			# Accounts module not installed, or ERPNext version pre-dates
			# the guard — nothing to warn about.
			return None
		settings = frappe.get_cached_doc("Repost Accounting Ledger Settings")
	except Exception:
		return None
	allowed_types = settings.get("allowed_types") or []
	allowed: set[str | None] = set()
	for row in allowed_types:
		if hasattr(row, "get"):
			# Tolerate both the current (``document_type``) and any
			# legacy / alternate (``doctype``) child fieldnames so we
			# don't break across ERPNext versions or custom forks.
			allowed.add(row.get("document_type"))
			allowed.add(row.get("doctype"))
	allowed.discard(None)
	if doctype in allowed:
		return None
	return (
		f"Heads-up: {doctype} is submitted and its controller emits GL "
		"entries, but it is not listed under Accounts → Repost "
		"Accounting Ledger Settings → Allowed Types.  Depending on "
		"which fields you change, ERPNext may refuse the apply with "
		f"'{doctype} is not allowed to be reposted.'  Add it to the "
		"allowed types (or have an admin do so) before clicking "
		"Confirm Update if you want a guaranteed-clean apply."
	)


def _locked_fields_on_submit(doctype: str, fieldnames: Any) -> list[str]:
	"""Return the subset of *fieldnames* that cannot be edited on a submitted doc.

	A field is editable post-submit only when its DocField row has
	``allow_on_submit = 1``.  Anything else is considered locked.
	"""
	try:
		import frappe

		meta = frappe.get_meta(doctype)
	except Exception:
		return []
	locked: list[str] = []
	for fn in fieldnames or []:
		if not fn:
			continue
		df = meta.get_field(fn) if hasattr(meta, "get_field") else None
		if df is None:
			# Unknown field — Frappe will throw on save; surface up-front.
			locked.append(fn)
			continue
		if not int(getattr(df, "allow_on_submit", 0) or 0):
			locked.append(fn)
	return locked


def _normalise(value: Any) -> Any:
	if isinstance(value, str):
		return value.strip()
	if isinstance(value, float):
		return round(value, 6)
	return value


__all__ = ["update_document"]
