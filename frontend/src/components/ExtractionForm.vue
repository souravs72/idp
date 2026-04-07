<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="space-y-6">
    <!-- Header fields -->
    <div>
      <h3 class="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
        Header Fields
      </h3>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div
          v-for="(value, fieldname) in header"
          :key="fieldname"
          class="space-y-1"
        >
          <label
            class="text-sm font-medium text-gray-600 dark:text-gray-400"
          >
            {{ fieldname }}
          </label>
          <input
            :value="value"
            type="text"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800"
            @input="$emit('update-header', fieldname, $event.target.value)"
          />
        </div>
      </div>
    </div>

    <!-- Line items -->
    <div v-if="items && items.length > 0">
      <h3 class="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
        Line Items ({{ items.length }})
      </h3>
      <div class="overflow-x-auto">
        <table
          class="min-w-full divide-y divide-gray-200 dark:divide-gray-700"
        >
          <thead class="bg-gray-50 dark:bg-gray-800">
            <tr>
              <th
                class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                #
              </th>
              <th
                v-for="col in itemColumns"
                :key="col"
                class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                {{ col }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
            <tr v-for="(row, idx) in items" :key="idx">
              <td class="whitespace-nowrap px-3 py-2 text-sm text-gray-500">
                {{ idx + 1 }}
              </td>
              <td v-for="col in itemColumns" :key="col" class="px-3 py-2">
                <input
                  :value="row[col]"
                  type="text"
                  class="w-full rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600 dark:bg-gray-800"
                  @input="
                    $emit('update-item', idx, col, $event.target.value)
                  "
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Unmapped fields -->
    <div v-if="unmappedFields && unmappedFields.length > 0">
      <h3
        class="mb-2 text-sm font-semibold text-amber-700 dark:text-amber-400"
      >
        Unmapped Fields ({{ unmappedFields.length }})
      </h3>
      <div class="space-y-1">
        <div
          v-for="(uf, idx) in unmappedFields"
          :key="idx"
          class="rounded bg-amber-50 px-3 py-1 text-sm dark:bg-amber-950"
        >
          <span class="font-medium">{{ uf.label }}:</span>
          {{ uf.value }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  header: { type: Object, default: () => ({}) },
  items: { type: Array, default: () => [] },
  unmappedFields: { type: Array, default: () => [] },
})

defineEmits(['update-header', 'update-item'])

const itemColumns = computed(() => {
  if (!props.items || props.items.length === 0) return []
  // Gather all unique keys across all rows
  const cols = new Set()
  for (const row of props.items) {
    for (const key of Object.keys(row)) {
      cols.add(key)
    }
  }
  return [...cols]
})
</script>
