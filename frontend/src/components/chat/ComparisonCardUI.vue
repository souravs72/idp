<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!-- Phase 36 D2 — ComparisonCard renderer.

  Renders the payload produced by the compare_document tool
  (idp/tools/compare_document.py).  The payload carries:
    - differences: [{fieldname, expected, actual, status}]
    - item_differences: [{index, fields: [{fieldname, expected, actual, status}]}]
    - summary: human-readable summary string

  Status values: "match" (green) / "mismatch" (amber) / "missing" (red),
  reusing the ConfidenceDot colour vocabulary.

  D3 action buttons:
    - "Update" → disabled until Phase 37 ships (UPDATE_DOC_ENABLED flag).
    - "Keep"   → marks row accepted in local state only; no backend call.
-->

<template>
  <div
    class="idp-comparison-card rounded-lg border border-blue-300 bg-blue-50 p-4 shadow-sm dark:border-blue-700 dark:bg-blue-950"
    role="region"
    :aria-label="`Comparison card: ${card.doctype || 'document'} ${card.name || ''}`"
  >
    <!-- Header -->
    <div class="mb-3 flex items-start gap-2">
      <span aria-hidden="true" class="text-base leading-none">🔍</span>
      <div>
        <div class="text-xs font-semibold uppercase tracking-wide text-blue-800 dark:text-blue-200">
          Document Comparison
        </div>
        <div class="mt-0.5 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {{ card.doctype }} · {{ card.name }}
        </div>
        <div v-if="card.summary" class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
          {{ card.summary }}
        </div>
      </div>
    </div>

    <!-- Empty state: all fields match -->
    <div
      v-if="allMatch"
      class="flex items-center gap-2 rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
    >
      <span aria-hidden="true">✓</span>
      All fields match
    </div>

    <!-- Header differences table -->
    <details v-if="!allMatch && differences.length" open class="mb-3">
      <summary class="cursor-pointer select-none text-xs font-medium text-gray-700 dark:text-gray-300">
        Field differences ({{ differences.length }})
      </summary>
      <div class="mt-2 overflow-x-auto rounded border border-gray-300 dark:border-gray-600">
        <table class="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th
                scope="col"
                class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              >
                Field
              </th>
              <th
                scope="col"
                class="border border-gray-300 bg-blue-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-blue-900 dark:text-gray-100"
              >
                Expected (file)
              </th>
              <th
                scope="col"
                class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              >
                Actual (ERPNext)
              </th>
              <th
                scope="col"
                class="border border-gray-300 bg-gray-100 px-2 py-1 text-center font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              >
                Status
              </th>
              <th
                scope="col"
                class="border border-gray-300 bg-gray-100 px-2 py-1 text-center font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="diff in differences"
              :key="diff.fieldname"
              :class="[rowBg(diff), accepted.has(diff.fieldname) ? 'opacity-50' : '']"
            >
              <td
                class="border border-gray-300 px-2 py-1.5 font-mono text-[11px] text-gray-700 dark:border-gray-600 dark:text-gray-300"
              >
                {{ diff.fieldname }}
              </td>
              <td
                class="border border-gray-300 px-2 py-1.5 text-gray-700 dark:border-gray-600 dark:text-gray-300"
                :class="accepted.has(diff.fieldname) ? 'line-through' : ''"
              >
                {{ formatValue(diff.expected) }}
              </td>
              <td class="border border-gray-300 px-2 py-1.5 text-gray-700 dark:border-gray-600 dark:text-gray-300">
                {{ formatValue(diff.actual) }}
              </td>
              <td class="border border-gray-300 px-2 py-1.5 text-center dark:border-gray-600">
                <span
                  class="inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                  :class="badgeClass(diff.status)"
                  :aria-label="ariaStatus(diff.status)"
                >
                  {{ diff.status }}
                </span>
              </td>
              <td class="border border-gray-300 px-2 py-1.5 text-center dark:border-gray-600">
                <div v-if="diff.status !== 'match'" class="flex items-center justify-center gap-1">
                  <!-- D3: Update — disabled until Phase 37 ships -->
                  <button
                    type="button"
                    :disabled="!updateEnabled || agentBusy"
                    :title="
                      updateEnabled
                        ? `Update ${card.doctype} ${card.name}: set ${diff.fieldname} to file value`
                        : 'Requires the update_document tool to be enabled'
                    "
                    class="rounded px-1.5 py-0.5 text-[10px] font-medium disabled:cursor-not-allowed disabled:opacity-40"
                    :class="
                      updateEnabled
                        ? 'bg-blue-600 text-white hover:bg-blue-700'
                        : 'bg-gray-200 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                    "
                    @click="onUpdate(diff)"
                  >
                    Update
                  </button>
                  <!-- D3: Keep ERPNext value — rewrites local card state only -->
                  <button
                    type="button"
                    :disabled="accepted.has(diff.fieldname)"
                    title="Keep the existing ERPNext value; ignore the file's value"
                    class="rounded border border-gray-300 px-1.5 py-0.5 text-[10px] font-medium hover:bg-gray-100 disabled:opacity-40 dark:border-gray-600 dark:hover:bg-gray-700"
                    @click="onAccept(diff.fieldname)"
                  >
                    Keep
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>

    <!-- Item differences (collapsed by default) -->
    <details v-if="itemDiffs.length" class="mb-2">
      <summary class="cursor-pointer select-none text-xs font-medium text-gray-700 dark:text-gray-300">
        Item differences ({{ itemDiffs.length }} row{{ itemDiffs.length === 1 ? '' : 's' }})
      </summary>
      <div v-for="row in itemDiffs" :key="row.index" class="mt-2">
        <div class="mb-1 text-[11px] font-medium text-gray-600 dark:text-gray-400">
          Row {{ row.index + 1 }}
        </div>
        <div class="overflow-x-auto rounded border border-gray-300 dark:border-gray-600">
          <table class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th scope="col" class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100">Field</th>
                <th scope="col" class="border border-gray-300 bg-blue-100 px-2 py-1 text-left font-semibold dark:border-gray-600 dark:bg-blue-900 dark:text-gray-100">Expected</th>
                <th scope="col" class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100">Actual</th>
                <th scope="col" class="border border-gray-300 bg-gray-100 px-2 py-1 text-center font-semibold dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="field in row.fields" :key="field.fieldname" :class="rowBg(field)">
                <td class="border border-gray-300 px-2 py-1 font-mono text-[11px] dark:border-gray-600">{{ field.fieldname }}</td>
                <td class="border border-gray-300 px-2 py-1 dark:border-gray-600">{{ formatValue(field.expected) }}</td>
                <td class="border border-gray-300 px-2 py-1 dark:border-gray-600">{{ formatValue(field.actual) }}</td>
                <td class="border border-gray-300 px-2 py-1 text-center dark:border-gray-600">
                  <span
                    class="inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                    :class="badgeClass(field.status)"
                    :aria-label="ariaStatus(field.status)"
                  >
                    {{ field.status }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </details>

    <div v-if="lastError" class="mt-2 text-xs text-red-700 dark:text-red-400">
      {{ lastError }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useAgent } from '@/composables/useAgent'

// Feature gate paired with the update_document tool — flipped once the
// tool was registered in the agent loop.
const UPDATE_DOC_ENABLED = true

const props = defineProps({
  message: { type: Object, required: true },
})

const { send, busy: agentBusy } = useAgent()
const lastError = ref(null)
const accepted = ref(new Set())

const updateEnabled = computed(() => UPDATE_DOC_ENABLED)

const card = computed(() => {
  const v = props.message.rendered_card_payload
  if (!v) return {}
  if (typeof v === 'object') return v
  try {
    return JSON.parse(v)
  } catch (_) {
    return {}
  }
})

const differences = computed(() => {
  const d = card.value.differences
  return Array.isArray(d) ? d : []
})

const itemDiffs = computed(() => {
  const d = card.value.item_differences
  if (!Array.isArray(d)) return []
  return d.filter((r) => r && Array.isArray(r.fields) && r.fields.length)
})

const allMatch = computed(
  () =>
    differences.value.length > 0 &&
    differences.value.every((d) => d.status === 'match'),
)

function badgeClass(status) {
  switch (status) {
    case 'match':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200'
    case 'mismatch':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'
    case 'missing':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
    default:
      return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
  }
}

function ariaStatus(status) {
  switch (status) {
    case 'match':
      return 'Match'
    case 'mismatch':
      return 'Mismatch'
    case 'missing':
      return 'Missing'
    default:
      return status || 'Unknown'
  }
}

function rowBg(diff) {
  switch (diff.status) {
    case 'mismatch':
      return 'bg-amber-50 dark:bg-amber-950/30'
    case 'missing':
      return 'bg-red-50 dark:bg-red-950/30'
    default:
      return 'odd:bg-white even:bg-gray-50 dark:odd:bg-gray-900 dark:even:bg-gray-800'
  }
}

function formatValue(v) {
  if (v == null || v === '') return '—'
  return String(v)
}

function onAccept(fieldname) {
  accepted.value = new Set([...accepted.value, fieldname])
}

async function onUpdate(diff) {
  if (!UPDATE_DOC_ENABLED || agentBusy.value) return
  lastError.value = null
  const doctype = card.value.doctype || ''
  const name = card.value.name || ''
  const content = `Update \`${doctype}\` \`${name}\` setting \`${diff.fieldname}\` = ${JSON.stringify(diff.expected)}`
  try {
    await send({ content })
  } catch (err) {
    lastError.value = err?.message || String(err)
  }
}
</script>
