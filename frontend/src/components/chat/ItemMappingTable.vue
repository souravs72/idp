<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 24 §24.0 — Item mapping table.

  Two-level header layout:

  | Extracted                            | ERPNext Item                | Status |
  | Item | Qty | UOM | Rate | Stock?     | Match | Score | Reason      |        |

  The component renders the items[] array produced by
  ``propose_create_document._build_item_row`` (see backend payload
  documented at the top of that module).

  Styling
  -------
  - table border: darker grey (``border-gray-400``)
  - header backgrounds: light blue (extracted) / light green (ERPNext)
  - body rows: zebra (``odd:`` stripe), hover light cyan, transitions
  - the ERPNext-side cells (match + is_stock_item) are *always* live
    inputs — the user can pick a different Item or toggle the stock
    flag without first clicking "Edit" on the ConfirmationCard.
-->

<template>
  <div class="overflow-x-auto rounded border border-gray-400 dark:border-gray-600">
    <table class="w-full border-collapse text-xs">
      <thead>
        <tr>
          <th
            colspan="5"
            class="border border-gray-400 bg-blue-100 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-blue-900 dark:text-gray-100"
          >
            Extracted
          </th>
          <th
            colspan="3"
            class="border border-gray-400 bg-green-100 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-green-900 dark:text-gray-100"
          >
            ERPNext Item
          </th>
          <th
            rowspan="2"
            class="border border-gray-400 bg-gray-100 px-2 py-1 text-center text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          >
            Status
          </th>
        </tr>
        <tr>
          <th class="border border-gray-400 bg-blue-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200">Item</th>
          <th class="border border-gray-400 bg-blue-50 px-2 py-1 text-right font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200">Qty</th>
          <th class="border border-gray-400 bg-blue-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200">UOM</th>
          <th class="border border-gray-400 bg-blue-50 px-2 py-1 text-right font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200">Rate</th>
          <th class="border border-gray-400 bg-blue-50 px-2 py-1 text-center font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200">
            Stock?
          </th>
          <th class="border border-gray-400 bg-green-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-green-950 dark:text-gray-200">Match</th>
          <th class="border border-gray-400 bg-green-50 px-2 py-1 text-right font-medium text-gray-700 dark:border-gray-600 dark:bg-green-950 dark:text-gray-200">Score</th>
          <th class="border border-gray-400 bg-green-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-green-950 dark:text-gray-200">
            Reason
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!rows.length">
          <td
            colspan="9"
            class="border border-gray-400 px-2 py-3 text-center text-gray-500 dark:border-gray-600 dark:text-gray-400"
          >
            No items extracted.
          </td>
        </tr>
        <tr
          v-for="row in rows"
          :key="row.index ?? row.row_index ?? row?.data?.item_code"
          class="odd:bg-white even:bg-gray-50 transition-colors hover:bg-cyan-50 dark:odd:bg-gray-900 dark:even:bg-gray-800 dark:hover:bg-cyan-950"
        >
          <!-- Extracted: combined Item (code + name) -->
          <td class="border border-gray-300 px-2 py-1 text-gray-700 dark:border-gray-700 dark:text-gray-300">
            <div class="font-medium">{{ formatItem(extracted(row)) }}</div>
            <div
              v-if="
                extracted(row).code &&
                extracted(row).name &&
                extracted(row).code !== extracted(row).name
              "
              class="text-[10px] text-gray-500 dark:text-gray-400"
            >
              {{ extracted(row).name }}
            </div>
          </td>
          <td class="border border-gray-300 px-2 py-1 text-right text-gray-700 dark:border-gray-700 dark:text-gray-300">
            {{ formatCell(extracted(row).qty) }}
          </td>
          <td class="border border-gray-300 px-2 py-1 text-gray-700 dark:border-gray-700 dark:text-gray-300">
            {{ formatCell(extracted(row).uom) }}
          </td>
          <td class="border border-gray-300 px-2 py-1 text-right text-gray-700 dark:border-gray-700 dark:text-gray-300">
            {{ formatCell(extracted(row).rate) }}
          </td>
          <td
            class="border border-gray-300 px-2 py-1 text-center text-gray-700 dark:border-gray-700 dark:text-gray-300"
          >
            <input
              type="checkbox"
              class="h-3.5 w-3.5 accent-amber-600 disabled:cursor-not-allowed disabled:opacity-50"
              :class="editing ? 'cursor-pointer' : ''"
              :checked="isStockItemChecked(row)"
              :disabled="!editing"
              @change="onStockItemToggle(row, $event.target.checked)"
            />
          </td>

          <!-- ERPNext Item: searchable dropdown (gated by edit mode) -->
          <td class="border border-gray-300 px-2 py-1 dark:border-gray-700">
            <div class="flex items-center gap-1" :ref="(el) => setAnchor(row.index, el)">
              <input
                v-model="localEdits[row.index]"
                class="w-full rounded border border-gray-300 bg-white px-1 py-0.5 text-xs focus:border-amber-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-gray-100 disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:disabled:bg-gray-800"
                :placeholder="row.erpnext_item || extracted(row).code || 'Search Item…'"
                :disabled="!editing"
                @input="onSearch(row.index, $event.target.value)"
                @focus="onFocus(row.index)"
                @blur="onBlur"
              />
              <button
                type="button"
                class="rounded border border-gray-300 px-1 text-[10px] text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                tabindex="-1"
                :disabled="!editing"
                @mousedown.prevent="toggleDropdown(row.index)"
                aria-label="Show suggestions"
              >
                ▾
              </button>
            </div>
          </td>
          <td class="border border-gray-300 px-2 py-1 text-right text-gray-700 dark:border-gray-700 dark:text-gray-300">
            {{ formatScore(row.confidence) }}
          </td>
          <td class="border border-gray-300 px-2 py-1 text-gray-600 dark:border-gray-700 dark:text-gray-400">
            {{ row.match_reason || '—' }}
          </td>

          <!-- Status -->
          <td class="border border-gray-300 px-2 py-1 text-center dark:border-gray-700">
            <span :class="statusBadgeClass(row.status)">
              {{ row.status || 'New' }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!--
    Teleported dropdown: rendered at the document body so it floats
    above any ancestor with ``overflow: hidden`` / ``overflow-x: auto``
    (Phase 24 fix — the table wrapper clips absolutely-positioned
    children regardless of z-index).
  -->
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
        :key="cand.item_code"
        class="cursor-pointer border-b border-gray-100 px-2 py-1.5 last:border-b-0 hover:bg-cyan-50 dark:border-gray-800 dark:hover:bg-cyan-950"
        @mousedown.prevent="pickSuggestion(activeRow, cand)"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="truncate font-medium text-gray-800 dark:text-gray-100">
            {{ cand.item_code }}
          </span>
          <span class="shrink-0 text-[10px] text-gray-400">
            {{ formatScore(cand.score) }}
          </span>
        </div>
        <div
          v-if="cand.item_name && cand.item_name !== cand.item_code"
          class="truncate text-[10px] text-gray-500 dark:text-gray-400"
        >
          {{ cand.item_name }}
        </div>
      </li>
    </ul>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { searchItems } from '@/utils/api'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  editing: { type: Boolean, default: false },
})

const emit = defineEmits(['edit', 'edit-stock'])

// Map of row.index -> user-entered ERPNext Item override.
const localEdits = reactive({})
// Map of row.index -> last server-side suggestion list.
const suggestions = reactive({})
// Per-row override of the is_stock_item checkbox (Boolean).
const stockEdits = reactive({})
// Currently focused row (for showing the dropdown).
const activeRow = ref(null)
// Per-row debounce handle.
const debounceTimers = {}
// Per-row DOM anchor used to position the teleported dropdown.
const anchors = reactive({})
// Reactive page metrics so the dropdown follows scroll / resize.
const viewportTick = ref(0)

function setAnchor(index, el) {
  if (el) {
    anchors[index] = el
  } else {
    delete anchors[index]
  }
}

const dropdownStyle = computed(() => {
  // Touch viewportTick so this re-evaluates on scroll / resize.
  // eslint-disable-next-line no-unused-expressions
  viewportTick.value
  if (activeRow.value === null) return null
  const el = anchors[activeRow.value]
  if (!el || !el.getBoundingClientRect) return null
  const rect = el.getBoundingClientRect()
  // Width: at least the input cell, but allow growth up to 360px so
  // long item names aren't truncated.
  const width = Math.max(rect.width, 280)
  return {
    position: 'fixed',
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
    width: `${width}px`,
  }
})

function bumpViewport() {
  viewportTick.value++
}

onMounted(() => {
  window.addEventListener('scroll', bumpViewport, true)
  window.addEventListener('resize', bumpViewport)
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', bumpViewport, true)
  window.removeEventListener('resize', bumpViewport)
})

watch(
  () => props.rows,
  (rows) => {
    for (const row of rows || []) {
      if (row?.index != null && localEdits[row.index] === undefined) {
        localEdits[row.index] = row.erpnext_item || ''
      }
      // Seed suggestions from any server-side candidates included in the
      // card payload so the dropdown shows hints before the user types.
      if (row?.index != null && !suggestions[row.index]) {
        const cands = row.match_candidates || []
        if (cands.length) {
          suggestions[row.index] = cands.slice(0, 10)
        }
      }
    }
  },
  { immediate: true, deep: false },
)

function onSearch(index, value) {
  if (!props.editing) return
  emit('edit', { index, value })
  if (debounceTimers[index]) clearTimeout(debounceTimers[index])
  const q = (value || '').trim()
  if (!q) {
    suggestions[index] = []
    return
  }
  debounceTimers[index] = setTimeout(async () => {
    try {
      const out = await searchItems({ query: q, topN: 10 })
      suggestions[index] = Array.isArray(out)
        ? out
        : Array.isArray(out?.message)
          ? out.message
          : []
    } catch (_err) {
      suggestions[index] = []
    }
  }, 200)
}

function onFocus(index) {
  if (!props.editing) return
  activeRow.value = index
  // If we already have seeded candidates but the user hasn't typed, show them.
  if (!(suggestions[index] || []).length) {
    const seedRow = (props.rows || []).find((r) => r?.index === index)
    const cands = seedRow?.match_candidates || []
    if (cands.length) suggestions[index] = cands.slice(0, 10)
  }
  // Force a position recompute on next tick so the teleported panel
  // lands under the input even if the page scrolled before focus.
  nextTick(() => bumpViewport())
}

function toggleDropdown(index) {
  if (!props.editing) return
  if (activeRow.value === index) {
    activeRow.value = null
  } else {
    onFocus(index)
  }
}

function pickSuggestion(index, cand) {
  if (!props.editing || !cand?.item_code) return
  localEdits[index] = cand.item_code
  emit('edit', { index, value: cand.item_code })
  suggestions[index] = []
  activeRow.value = null
}

function onBlur() {
  // Defer so a click on the dropdown still fires its mousedown handler.
  setTimeout(() => {
    activeRow.value = null
  }, 150)
}

function extracted(row) {
  const data = (row && row.data) || {}
  return {
    code: data.item_code || data.item || data.code || '',
    name: data.item_name || data.description || '',
    qty: data.qty,
    uom: data.uom || data.unit || '',
    rate: data.rate ?? data.price ?? data.amount,
    is_stock_item: data.is_stock_item,
  }
}

function isStockItemChecked(row) {
  if (row?.index != null && stockEdits[row.index] !== undefined) {
    return !!stockEdits[row.index]
  }
  const v = extracted(row).is_stock_item
  if (typeof v === 'boolean') return v
  if (typeof v === 'number') return !!v
  if (typeof v === 'string') {
    const s = v.trim().toLowerCase()
    return ['1', 'true', 'yes', 'y'].includes(s)
  }
  return false
}

function onStockItemToggle(row, checked) {
  if (!props.editing) return
  if (row?.index == null) return
  stockEdits[row.index] = !!checked
  emit('edit-stock', { index: row.index, value: !!checked })
}

function formatItem(ex) {
  // Show the item code if present, else the name; the description (if
  // distinct) is rendered on a second line.
  return ex.code || ex.name || '—'
}

function formatCell(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function formatScore(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

function statusBadgeClass(status) {
  const base =
    'inline-block rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide'
  if (status === 'Existing') {
    return `${base} bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100`
  }
  if (status === 'New') {
    return `${base} bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100`
  }
  return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200`
}
</script>
