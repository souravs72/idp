<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="space-y-6">
    <!-- Header field comparison -->
    <div>
      <h3 class="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
        Header Fields
      </h3>
      <div class="overflow-x-auto">
        <table
          class="min-w-full divide-y divide-gray-200 dark:divide-gray-700"
        >
          <thead class="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                Status
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                Field
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                Document
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                Record
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
            <tr v-for="field in allHeaderFields" :key="field.field">
              <td class="whitespace-nowrap px-4 py-2">
                <StatusBadge :status="field.status" />
              </td>
              <td class="px-4 py-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                {{ field.label }}
              </td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">
                {{ field.document_value ?? '—' }}
              </td>
              <td class="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">
                {{ field.record_value ?? '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Item-level comparison -->
    <div v-if="itemsComparison && itemsComparison.length > 0">
      <h3 class="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
        Line Items
      </h3>
      <div
        v-for="(item, idx) in itemsComparison"
        :key="idx"
        class="mb-4 rounded-lg border border-gray-200 p-3 dark:border-gray-700"
      >
        <div class="mb-2 flex items-center gap-2">
          <StatusBadge :status="item.status" />
          <span class="font-medium text-gray-900 dark:text-gray-100">
            {{ item.item_name || item.item_code || `Row ${idx + 1}` }}
          </span>
        </div>
        <table
          v-if="item.field_comparisons && item.field_comparisons.length > 0"
          class="min-w-full divide-y divide-gray-100 dark:divide-gray-800"
        >
          <tbody>
            <tr
              v-for="fc in item.field_comparisons"
              :key="fc.field"
              :class="fc.status === 'mismatch' ? 'bg-red-50 dark:bg-red-950' : ''"
            >
              <td class="px-3 py-1 text-xs text-gray-500">
                {{ fc.label }}
              </td>
              <td class="px-3 py-1 text-xs">
                {{ fc.document_value ?? '—' }}
              </td>
              <td class="px-3 py-1 text-xs">
                {{ fc.record_value ?? '—' }}
              </td>
              <td class="px-3 py-1">
                <StatusBadge :status="fc.status" size="sm" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Summary -->
    <div
      v-if="summary"
      class="rounded-lg bg-gray-50 p-4 text-sm text-gray-700 dark:bg-gray-800 dark:text-gray-300"
    >
      {{ summary }}
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatusBadge from './StatusBadge.vue'

const props = defineProps({
  matches: { type: Array, default: () => [] },
  discrepancies: { type: Array, default: () => [] },
  itemsComparison: { type: Array, default: () => [] },
  summary: { type: String, default: '' },
})

const allHeaderFields = computed(() => [
  ...props.matches,
  ...props.discrepancies,
])
</script>
