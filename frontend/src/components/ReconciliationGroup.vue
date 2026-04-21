<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="rounded-lg border" :class="borderClasses">
    <div class="flex items-center justify-between px-4 py-2 text-sm font-semibold" :class="headerClasses">
      <span>{{ title }}</span>
      <span class="text-xs opacity-80">{{ rows.length }}</span>
    </div>
    <div class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Date
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Description
            </th>
            <th class="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">
              Amount
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Ref
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              ERPNext Match
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Score
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
          <template v-for="(row, idx) in rows" :key="idx">
            <tr>
              <td class="whitespace-nowrap px-3 py-2 text-xs">
                {{ row.transaction.date }}
              </td>
              <td class="px-3 py-2 text-xs">
                {{ row.transaction.description }}
              </td>
              <td
                class="whitespace-nowrap px-3 py-2 text-right text-xs"
                :class="amountClass(row.transaction)"
              >
                {{ formatAmount(row.transaction) }}
              </td>
              <td class="px-3 py-2 text-xs text-gray-500">
                {{ row.transaction.reference || '—' }}
              </td>
              <td class="px-3 py-2 text-xs">
                <div v-if="row.selected">
                  <div class="font-medium">
                    {{ row.selected.doctype }} / {{ row.selected.name }}
                  </div>
                  <div class="text-[11px] text-gray-500">
                    {{ row.selected.posting_date }}
                    <span v-if="row.selected.party"> — {{ row.selected.party }}</span>
                    <span v-if="row.selected.reference_no">
                      — ref {{ row.selected.reference_no }}
                    </span>
                  </div>
                </div>
                <span v-else class="text-gray-400">—</span>
              </td>
              <td class="px-3 py-2 text-xs">
                <span v-if="row.selected">
                  {{ row.selected.match_type }} ({{ row.selected.score }})
                </span>
                <span v-else class="text-gray-400">—</span>
              </td>
            </tr>
            <!-- Notes -->
            <tr v-if="row.notes">
              <td colspan="6" class="bg-amber-50 px-3 py-1 text-[11px] italic text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                {{ row.notes }}
              </td>
            </tr>
            <!-- Full candidate list (for multiple_matches) -->
            <tr v-if="showAllCandidates && row.candidates && row.candidates.length > 1">
              <td colspan="6" class="bg-gray-50 px-3 py-2 dark:bg-gray-900">
                <div class="text-[11px] text-gray-500 mb-1">Candidates:</div>
                <ul class="space-y-1">
                  <li
                    v-for="(c, ci) in row.candidates"
                    :key="ci"
                    class="flex items-center justify-between text-[11px]"
                  >
                    <span>
                      <strong>{{ c.doctype }}</strong> / {{ c.name }}
                      — {{ c.posting_date }}
                      <span v-if="c.party"> — {{ c.party }}</span>
                      <span v-if="c.reference_no"> — ref {{ c.reference_no }}</span>
                    </span>
                    <span class="text-gray-500">
                      {{ c.match_type }} ({{ c.score }})
                    </span>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  tone: { type: String, default: 'success' }, // success | warning | danger
  rows: { type: Array, default: () => [] },
  showAllCandidates: { type: Boolean, default: false },
})

const borderClasses = computed(() => {
  switch (props.tone) {
    case 'success':
      return 'border-green-200 dark:border-green-900'
    case 'warning':
      return 'border-amber-200 dark:border-amber-900'
    case 'danger':
      return 'border-red-200 dark:border-red-900'
    default:
      return 'border-gray-200 dark:border-gray-700'
  }
})

const headerClasses = computed(() => {
  switch (props.tone) {
    case 'success':
      return 'bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200'
    case 'warning':
      return 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
    case 'danger':
      return 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200'
    default:
      return 'bg-gray-50 text-gray-800 dark:bg-gray-800 dark:text-gray-200'
  }
})

function formatAmount(txn) {
  const value =
    txn.credit != null && txn.credit !== ''
      ? Number(txn.credit)
      : txn.debit != null && txn.debit !== ''
        ? -Number(txn.debit)
        : 0
  if (Number.isNaN(value)) return '—'
  const sign = value < 0 ? '-' : ''
  return (
    sign +
    Math.abs(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  )
}

function amountClass(txn) {
  if (txn.credit != null && txn.credit !== '') {
    return 'text-green-600 dark:text-green-400'
  }
  if (txn.debit != null && txn.debit !== '') {
    return 'text-red-600 dark:text-red-400'
  }
  return ''
}
</script>
