<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 25 §25.1 — Generic child-table renderer.

  Sibling of :file:`ItemMappingTable.vue`, used by the ConfirmationCard
  whenever the target DocType's primary child table isn't ``items``
  (Journal Entry → ``accounts``, Payment Entry → ``references``,
  Payroll Entry → ``employees``, etc.).

  Columns are derived from ``child_row_schema`` on the card payload —
  one column per fieldname, ordered as supplied by the backend.
  ``source_page`` (Phase 25 §25.2) renders as a small breadcrumb on
  the leftmost cell.

  All cells become editable inputs while the parent card is in Edit
  mode.  Edits are emitted as ``edit-cell`` events; the parent
  composable collects them and forwards everything as ``row_edits``
  on confirm.
-->

<template>
  <div class="overflow-x-auto rounded border border-gray-400 dark:border-gray-600">
    <table class="w-full border-collapse text-xs">
      <thead>
        <tr>
          <th
            class="border border-gray-400 bg-gray-100 px-2 py-1 text-center text-[11px] font-semibold uppercase tracking-wide text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          >
            #
          </th>
          <th
            v-for="col in columns"
            :key="col.fieldname"
            class="border border-gray-400 bg-blue-50 px-2 py-1 text-left font-medium text-gray-700 dark:border-gray-600 dark:bg-blue-950 dark:text-gray-200"
          >
            {{ col.label }}
            <span
              v-if="col.reqd"
              class="text-red-500"
              aria-label="required"
            >*</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!rows.length">
          <td
            :colspan="columns.length + 1"
            class="border border-gray-400 px-2 py-3 text-center text-gray-500 dark:border-gray-600 dark:text-gray-400"
          >
            No rows extracted.
          </td>
        </tr>
        <tr
          v-for="row in rows"
          :key="row.index ?? row.row_index"
          class="odd:bg-white even:bg-gray-50 transition-colors hover:bg-cyan-50 dark:odd:bg-gray-900 dark:even:bg-gray-800 dark:hover:bg-cyan-950"
        >
          <td
            class="border border-gray-300 px-2 py-1 text-center text-gray-500 dark:border-gray-700 dark:text-gray-400"
          >
            <div>{{ (row.index ?? 0) + 1 }}</div>
            <div
              v-if="row.source_page"
              class="text-[10px] text-gray-400"
              :title="`From page ${row.source_page}`"
            >
              p.{{ row.source_page }}
            </div>
          </td>
          <td
            v-for="col in columns"
            :key="col.fieldname"
            class="border border-gray-300 px-2 py-1 text-gray-700 dark:border-gray-700 dark:text-gray-300"
          >
            <span v-if="!editing">{{ formatCell(row, col) }}</span>
            <input
              v-else-if="col.fieldtype === 'Check'"
              type="checkbox"
              :checked="readCell(row, col) ? true : false"
              class="h-4 w-4 rounded border-gray-300 dark:border-gray-600"
              @change="onEdit(row, col, $event.target.checked ? 1 : 0)"
            />
            <input
              v-else
              :type="inputType(col)"
              :value="readCell(row, col) ?? ''"
              class="w-full rounded border border-gray-300 bg-white px-1 py-0.5 text-xs focus:border-amber-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900"
              @input="onEdit(row, col, $event.target.value)"
            />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rows: { type: Array, required: true, default: () => [] },
  // Column schema derived server-side from the child DocType's meta
  // (Phase 25 §25.1).  Each entry: ``{fieldname, fieldtype, label,
  // reqd, options}``.  When empty (legacy cards) we fall back to the
  // keys actually present on the first row.
  schema: { type: Array, default: () => [] },
  editing: { type: Boolean, default: false },
})

const emit = defineEmits(['edit-cell'])

const _NUMERIC_TYPES = new Set([
  'Int',
  'Float',
  'Currency',
  'Percent',
])
const _HIDDEN_TYPES = new Set([
  'Section Break',
  'Column Break',
  'Tab Break',
  'HTML',
  'Button',
  'Image',
  'Heading',
  'Fold',
  'Read Only',
])

const columns = computed(() => {
  const schemaCols = (props.schema || []).filter(
    (f) => f && f.fieldname && !_HIDDEN_TYPES.has(f.fieldtype),
  )
  if (schemaCols.length) return schemaCols
  // Fallback — derive columns from the first row's keys.
  const first = props.rows?.[0]?.data
  if (!first || typeof first !== 'object') return []
  return Object.keys(first)
    .filter((k) => k !== 'source_page')
    .map((k) => ({
      fieldname: k,
      fieldtype: 'Data',
      label: titleCase(k),
      reqd: 0,
      options: '',
    }))
})

function titleCase(s) {
  return String(s || '')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

function readCell(row, col) {
  const data = row?.data || {}
  return data[col.fieldname]
}

function formatCell(row, col) {
  const v = readCell(row, col)
  if (v == null || v === '') return '—'
  if (col.fieldtype === 'Check') return v ? '✓' : '—'
  if (_NUMERIC_TYPES.has(col.fieldtype)) {
    const n = Number(v)
    if (Number.isFinite(n)) return n.toLocaleString()
  }
  return String(v)
}

function inputType(col) {
  if (_NUMERIC_TYPES.has(col.fieldtype)) return 'number'
  if (col.fieldtype === 'Date') return 'date'
  if (col.fieldtype === 'Datetime') return 'datetime-local'
  return 'text'
}

function onEdit(row, col, value) {
  const idx = row?.index ?? row?.row_index
  if (idx == null) return
  // Coerce numeric strings so downstream validators see real numbers.
  let v = value
  if (_NUMERIC_TYPES.has(col.fieldtype) && typeof v === 'string' && v !== '') {
    const n = Number(v)
    if (Number.isFinite(n)) v = n
  }
  emit('edit-cell', { index: idx, fieldname: col.fieldname, value: v })
}
</script>
