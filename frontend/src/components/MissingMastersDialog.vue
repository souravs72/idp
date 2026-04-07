<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <Dialog
    :options="{
      title: 'Missing Master Records',
      size: 'lg',
    }"
    v-model="show"
  >
    <template #body-content>
      <div class="space-y-4">
        <p class="text-sm text-gray-600 dark:text-gray-400">
          The following master records were not found in ERPNext. You can
          auto-create them or go back and update the extracted data.
        </p>

        <div class="divide-y divide-gray-200 dark:divide-gray-700">
          <div
            v-for="(master, idx) in missingMasters"
            :key="idx"
            class="flex items-center justify-between py-3"
          >
            <div>
              <span
                class="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300"
              >
                {{ master.doctype }}
              </span>
              <span class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                {{ master.value || master.name }}
              </span>
            </div>
            <span class="text-xs text-gray-500">
              Field: {{ master.fieldname }}
            </span>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 pt-2">
          <button
            class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
            @click="show = false"
          >
            Go Back
          </button>
          <button
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            @click="$emit('create-masters')"
          >
            Auto-Create &amp; Continue
          </button>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog } from 'frappe-ui'

const show = defineModel({ type: Boolean, default: false })

defineProps({
  missingMasters: { type: Array, default: () => [] },
})

defineEmits(['create-masters'])
</script>
