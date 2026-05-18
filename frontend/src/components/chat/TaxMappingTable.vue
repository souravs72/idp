<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 24 §24.4 — Tax mapping table.

  Two-level header layout:

  | Extracted                       | ERPNext Account | Status |
  | Account | Rate | Tax Amount     | Match           |        |

  Styling matches ItemMappingTable: darker grey table border, light
  blue header on the Extracted side, light green on the ERPNext side,
  zebra body with hover light cyan.  The ERPNext Account picker is
  gated by `editing` — disabled until the user clicks "Edit".

  The dropdown is rendered through a `<Teleport to="body">` portal so
  it is not clipped by the parent `overflow-x-auto` container.
-->

<template>
	<div class="overflow-x-auto rounded border border-gray-400 dark:border-gray-600">
		<table class="w-full border-collapse text-xs">
			<thead>
				<tr>
					<th
						colspan="3"
						class="border border-gray-400 bg-blue-100 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-blue-900 dark:text-gray-100"
					>
						Extracted
					</th>
					<th
						class="border border-gray-400 bg-green-100 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-green-900 dark:text-gray-100"
					>
						ERPNext Account
					</th>
					<th
						rowspan="2"
						class="border border-gray-400 bg-gray-100 px-2 py-1 text-center text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
					>
						Status
					</th>
				</tr>
				<tr>
					<th
						class="border border-gray-400 bg-blue-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200"
					>
						Account
					</th>
					<th
						class="border border-gray-400 bg-blue-50 px-2 py-1 text-right font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200"
					>
						Rate
					</th>
					<th
						class="border border-gray-400 bg-blue-50 px-2 py-1 text-right font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200"
					>
						Tax Amount
					</th>
					<th
						class="border border-gray-400 bg-green-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-green-950 dark:text-gray-200"
					>
						Match
					</th>
				</tr>
			</thead>
			<tbody>
				<tr v-if="!rows.length">
					<td
						colspan="5"
						class="border border-gray-400 px-2 py-3 text-center text-gray-500 dark:border-gray-600 dark:text-gray-400"
					>
						No taxes extracted.
					</td>
				</tr>
				<tr
					v-for="row in rows"
					:key="row.row_index ?? row?.extracted?.account"
					class="odd:bg-white even:bg-gray-50 transition-colors hover:bg-cyan-50 dark:odd:bg-gray-900 dark:even:bg-gray-800 dark:hover:bg-cyan-950"
				>
					<!-- Extracted -->
					<td
						data-label="Account"
						class="border border-gray-300 px-2 py-1 text-gray-700 dark:border-gray-700 dark:text-gray-300"
					>
						{{ formatCell(row?.extracted?.account) }}
					</td>
					<td
						data-label="Rate"
						class="border border-gray-300 px-2 py-1 text-right text-gray-700 dark:border-gray-700 dark:text-gray-300"
					>
						{{ formatRate(row?.extracted?.rate) }}
					</td>
					<td
						data-label="Tax Amount"
						class="border border-gray-300 px-2 py-1 text-right text-gray-700 dark:border-gray-700 dark:text-gray-300"
					>
						{{ formatCell(row?.extracted?.tax_amount) }}
					</td>

					<!-- ERPNext Account: searchable dropdown (gated by editing) -->
					<td
						data-label="Match"
						class="border border-gray-300 px-2 py-1 dark:border-gray-700"
					>
						<div
							class="flex items-center gap-1"
							:ref="(el) => setAnchor(row.row_index, el)"
						>
							<input
								v-model="localEdits[row.row_index]"
								class="w-full rounded border border-gray-300 bg-white px-1 py-0.5 text-xs focus:border-amber-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:disabled:bg-gray-800"
								:class="{
									'border-red-400 placeholder:text-red-500 dark:border-red-500 dark:placeholder:text-red-400':
										!row.erpnext_account,
								}"
								:placeholder="placeholderFor(row)"
								:disabled="!editing"
								@input="onSearch(row.row_index, $event.target.value)"
								@focus="onFocus(row.row_index)"
								@blur="onBlur"
							/>
							<button
								type="button"
								class="rounded border border-gray-300 px-1 text-[10px] text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
								tabindex="-1"
								:disabled="!editing"
								@mousedown.prevent="toggleDropdown(row.row_index)"
								aria-label="Show suggestions"
							>
								▾
							</button>
						</div>
					</td>
					<!-- Status (with Phase 29 confidence dot) -->
					<td
						data-label="Status"
						class="border border-gray-300 px-2 py-1 text-center dark:border-gray-700"
					>
						<div class="inline-flex items-center gap-1.5">
							<ConfidenceDot
								:band="row.confidence_band"
								:value="typeof row.confidence === 'number' ? row.confidence : null"
								size="sm"
							/>
							<span :class="statusBadgeClass(row.status)">
								{{ row.status || "New" }}
							</span>
						</div>
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<!-- Teleported dropdown — escapes the overflow-x-auto clip -->
	<Teleport to="body">
		<ul
			v-if="
				activeRow !== null &&
				editing &&
				(suggestions[activeRow] || []).length &&
				dropdownStyle
			"
			class="z-[1000] max-h-72 overflow-y-auto rounded border border-gray-300 bg-white text-xs shadow-lg dark:border-gray-700 dark:bg-gray-900"
			:style="dropdownStyle"
		>
			<li
				v-for="cand in suggestions[activeRow]"
				:key="cand.account_name || cand.name"
				class="cursor-pointer px-2 py-1 hover:bg-cyan-50 dark:hover:bg-cyan-950"
				@mousedown.prevent="pickSuggestion(activeRow, cand)"
			>
				<div class="truncate font-medium text-gray-800 dark:text-gray-100">
					{{ cand.account_name || cand.name }}
				</div>
				<div class="truncate text-[10px] text-gray-500 dark:text-gray-400">
					{{ cand.display_name || cand.account_name || cand.name }}
					<span class="ml-1 text-gray-400">({{ formatScore(cand.score) }})</span>
				</div>
			</li>
		</ul>
	</Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { searchAccounts } from "@/utils/api";
import ConfidenceDot from "./ConfidenceDot.vue";

const props = defineProps({
	rows: { type: Array, default: () => [] },
	editing: { type: Boolean, default: false },
	company: { type: String, default: null },
});

const emit = defineEmits(["edit"]);

// Map of row_index -> user-entered ERPNext Account override.
const localEdits = reactive({});
// Map of row_index -> server-side suggestions list.
const suggestions = reactive({});
const activeRow = ref(null);
const debounceTimers = {};

// Per-row anchor element refs (the input wrapper) so the teleported
// dropdown can be positioned via getBoundingClientRect().
const anchors = reactive({});
const viewportTick = ref(0);

function setAnchor(index, el) {
	if (el) {
		anchors[index] = el;
	} else {
		delete anchors[index];
	}
}

function bumpViewport() {
	viewportTick.value++;
}

onMounted(() => {
	window.addEventListener("scroll", bumpViewport, true);
	window.addEventListener("resize", bumpViewport);
});

onBeforeUnmount(() => {
	window.removeEventListener("scroll", bumpViewport, true);
	window.removeEventListener("resize", bumpViewport);
});

const dropdownStyle = computed(() => {
	// Touch tick so the computed re-runs on scroll/resize.
	// eslint-disable-next-line no-unused-expressions
	viewportTick.value;
	if (activeRow.value === null) return null;
	const el = anchors[activeRow.value];
	if (!el || !el.getBoundingClientRect) return null;
	const rect = el.getBoundingClientRect();
	const width = Math.max(rect.width, 280);
	return {
		position: "fixed",
		top: `${rect.bottom + 4}px`,
		left: `${rect.left}px`,
		width: `${width}px`,
	};
});

watch(
	() => props.rows,
	(rows) => {
		for (const row of rows || []) {
			if (row?.row_index != null && localEdits[row.row_index] === undefined) {
				localEdits[row.row_index] = row.erpnext_account || "";
			}
			if (row?.row_index != null && !suggestions[row.row_index]) {
				const cands = row.match_candidates || [];
				if (cands.length) {
					suggestions[row.row_index] = cands.slice(0, 10);
				}
			}
		}
	},
	{ immediate: true, deep: false },
);

function onSearch(index, value) {
	if (!props.editing) return;
	emit("edit", { index, value });
	if (debounceTimers[index]) clearTimeout(debounceTimers[index]);
	const q = (value || "").trim();
	if (!q) {
		suggestions[index] = [];
		return;
	}
	debounceTimers[index] = setTimeout(async () => {
		try {
			const out = await searchAccounts({
				query: q,
				company: props.company || undefined,
				topN: 10,
			});
			suggestions[index] = Array.isArray(out)
				? out
				: Array.isArray(out?.message)
					? out.message
					: [];
		} catch (_err) {
			suggestions[index] = [];
		}
	}, 200);
}

function onFocus(index) {
	if (!props.editing) return;
	activeRow.value = index;
	bumpViewport();
	if (!(suggestions[index] || []).length) {
		const seedRow = (props.rows || []).find((r) => r?.row_index === index);
		const cands = seedRow?.match_candidates || [];
		if (cands.length) suggestions[index] = cands.slice(0, 10);
	}
}

function toggleDropdown(index) {
	if (!props.editing) return;
	if (activeRow.value === index) {
		activeRow.value = null;
	} else {
		onFocus(index);
	}
}

function pickSuggestion(index, cand) {
	if (!props.editing) return;
	const value = cand?.account_name || cand?.name;
	if (!value) return;
	localEdits[index] = value;
	emit("edit", { index, value });
	suggestions[index] = [];
	activeRow.value = null;
}

function onBlur() {
	setTimeout(() => {
		activeRow.value = null;
	}, 150);
}

function formatCell(v) {
	if (v === null || v === undefined || v === "") return "—";
	if (typeof v === "object") return JSON.stringify(v);
	return String(v);
}

// Placeholder distinguishes mapped rows (greyed-out resolved Account)
// from unmapped rows.  Falling back to ``extracted.account`` here would
// silently render the raw OCR label (e.g. "IGST") inside an empty
// dropdown — the user then mistakes it for a real ERPNext Account
// match.  When ``erpnext_account`` is blank we surface an explicit
// "Unmapped — pick an Account" prompt instead so the action item is
// obvious.
function placeholderFor(row) {
	if (row?.erpnext_account) return row.erpnext_account;
	const label = row?.extracted?.account || "";
	if (label) return `Unmapped (${label}) — pick an Account…`;
	return "Unmapped — pick an Account…";
}

function formatRate(v) {
	if (v === null || v === undefined || v === "") return "—";
	const n = Number(v);
	if (Number.isNaN(n)) return String(v);
	// Treat values <= 1 as fractional rates (0.18 -> 18%); larger as percent already.
	const pct = n <= 1 ? n * 100 : n;
	return `${pct.toFixed(2)}%`;
}

function formatScore(v) {
	if (v === null || v === undefined) return "—";
	const n = Number(v);
	if (Number.isNaN(n)) return "—";
	return n.toFixed(2);
}

function statusBadgeClass(status) {
	const base =
		"inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide";
	if (status === "Existing") {
		return `${base} bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100`;
	}
	if (status === "New") {
		return `${base} bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100`;
	}
	return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200`;
}
</script>
