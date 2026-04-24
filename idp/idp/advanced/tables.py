# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""§15.5 — Advanced table handlers.

Post-processors that run *after* PaddleOCR / PP-Structure has returned
its raw tables, handling three awkward cases the core pipeline treats
as edge cases:

* **Multi-page continuation tables** -- a table whose header row appears
  once (page 1) and whose data rows continue on subsequent pages.
* **Borderless / space-aligned tables** -- rows detected as plain text
  that can be re-gridded using column-header x-coordinates.
* **Nested tables** -- cells that themselves contain tab/newline-
  separated sub-rows, flattened into the parent grid.

None of these mutate the core :class:`ExtractionResult`; the helpers
return a new ``list[list[list[str]]]`` which callers can merge back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from idp.core.logger import get_logger

logger = get_logger("idp.advanced.tables")


# ---------------------------------------------------------------------------
# Multi-page continuation
# ---------------------------------------------------------------------------


def merge_multipage_tables(
	tables: list[list[list[str]]],
	*,
	min_header_overlap: float = 0.6,
) -> list[list[list[str]]]:
	"""Merge tables from consecutive pages when their headers align.

	``min_header_overlap`` -- fraction of header cells that must match
	(case-insensitive, whitespace-normalised) for two tables to be
	considered the same continued table.  Default 60%.

	The first table keeps its header; subsequent tables contribute only
	their data rows.
	"""
	if len(tables) <= 1:
		return tables

	merged: list[list[list[str]]] = []
	current: list[list[str]] | None = None

	for tbl in tables:
		if not tbl:
			continue
		if current is None:
			current = [list(row) for row in tbl]
			continue

		if _headers_match(current[0], tbl[0], min_header_overlap):
			# Drop header of the continuation, append its data rows
			current.extend(list(r) for r in tbl[1:])
			logger.debug("Merged continuation table (%d new rows)", len(tbl) - 1)
		else:
			merged.append(current)
			current = [list(row) for row in tbl]

	if current is not None:
		merged.append(current)
	return merged


def _headers_match(a: list[str], b: list[str], threshold: float) -> bool:
	if not a or not b:
		return False
	norm_a = [_norm_cell(c) for c in a]
	norm_b = [_norm_cell(c) for c in b]
	common = sum(1 for c in norm_a if c and c in norm_b)
	denom = max(len(norm_a), len(norm_b))
	return (common / denom) >= threshold if denom else False


def _norm_cell(value: str) -> str:
	return re.sub(r"\s+", " ", (value or "").strip().lower())


# ---------------------------------------------------------------------------
# Borderless / space-aligned tables
# ---------------------------------------------------------------------------


@dataclass
class _ColumnSpan:
	start: int
	end: int
	header: str


def detect_borderless_table(text_block: str, *, min_columns: int = 3) -> list[list[str]] | None:
	"""Re-grid a block of space-aligned text into a table.

	Works when:

	* The first non-empty line is a header with ``>= min_columns`` gap-
	  separated tokens (2+ spaces between columns).
	* Subsequent lines share the same column x-offsets (rounded to the
	  nearest space boundary).

	Returns ``None`` if the block doesn't look like a table.
	"""
	lines = [ln.rstrip() for ln in (text_block or "").splitlines() if ln.strip()]
	if len(lines) < 2:
		return None

	header_spans = _detect_column_spans(lines[0])
	if len(header_spans) < min_columns:
		return None

	grid: list[list[str]] = [[s.header for s in header_spans]]
	for line in lines[1:]:
		row = _slice_by_spans(line, header_spans)
		if any(cell for cell in row):
			grid.append(row)

	if len(grid) < 2:
		return None
	logger.debug("Borderless table detected: %d rows x %d cols", len(grid), len(header_spans))
	return grid


def _detect_column_spans(header: str) -> list[_ColumnSpan]:
	"""Find ``(start, end, label)`` for each column, splitting on 2+ spaces."""
	spans: list[_ColumnSpan] = []
	# Find runs of non-whitespace separated by >= 2 spaces
	for match in re.finditer(r"\S+(?:\s\S+)*", header):
		text = match.group()
		start = match.start()
		end = match.end()
		# Merge adjacent tokens separated by a single space
		if spans and (start - spans[-1].end) < 2:
			spans[-1] = _ColumnSpan(spans[-1].start, end, (spans[-1].header + " " + text).strip())
		else:
			spans.append(_ColumnSpan(start, end, text))
	return spans


def _slice_by_spans(line: str, spans: list[_ColumnSpan]) -> list[str]:
	"""Cut *line* at the column boundaries of *spans*."""
	# Extend line to cover last span
	padded = line.ljust(spans[-1].end)
	cells: list[str] = []
	for i, span in enumerate(spans):
		start = span.start
		end = spans[i + 1].start if i + 1 < len(spans) else len(padded)
		cells.append(padded[start:end].strip())
	return cells


# ---------------------------------------------------------------------------
# Nested table flattening
# ---------------------------------------------------------------------------


def flatten_nested_cells(table: list[list[str]], *, separator: str = "\n") -> list[list[str]]:
	"""Expand cells that contain multi-line sub-rows.

	If a single data cell contains newline-separated values, the row is
	duplicated so every combination of sub-values is emitted.  Limits
	expansion to cells with at most ``8`` sub-entries to avoid blowing
	up when a cell happens to hold a paragraph.
	"""
	if not table or len(table) < 2:
		return table

	header = table[0]
	out: list[list[str]] = [list(header)]

	for row in table[1:]:
		# Identify sub-row candidates
		split_cells: list[list[str]] = []
		fan_out = 1
		for cell in row:
			parts = [p.strip() for p in (cell or "").split(separator) if p.strip()]
			if 1 < len(parts) <= 8:
				split_cells.append(parts)
				fan_out = max(fan_out, len(parts))
			else:
				split_cells.append([cell])

		# Build expanded rows
		for i in range(fan_out):
			new_row: list[str] = []
			for parts in split_cells:
				new_row.append(parts[i] if i < len(parts) else parts[-1])
			out.append(new_row)

	logger.debug("Nested flatten: %d -> %d rows", len(table), len(out))
	return out


# ---------------------------------------------------------------------------
# Convenience pipeline
# ---------------------------------------------------------------------------


def postprocess_tables(
	tables: list[list[list[str]]],
	*,
	merge_multipage: bool = True,
	flatten_nested: bool = True,
) -> list[list[list[str]]]:
	"""Apply the advanced handlers in the recommended order."""
	out = tables
	if merge_multipage:
		out = merge_multipage_tables(out)
	if flatten_nested:
		out = [flatten_nested_cells(t) for t in out]
	return out
