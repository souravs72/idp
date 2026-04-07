<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div
    class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900"
  >
    <!-- Validation status -->
    <div v-if="validationErrors.length > 0" class="mb-4">
      <div class="mb-2 text-sm font-semibold text-red-700 dark:text-red-400">
        Validation Errors ({{ validationErrors.length }})
      </div>
      <ul class="list-inside list-disc space-y-1 text-sm text-red-600">
        <li v-for="(err, idx) in validationErrors" :key="idx">
          <span v-if="err.field" class="font-medium">{{ err.field }}:</span>
          {{ err.message }}
        </li>
      </ul>
    </div>

    <div v-if="validationWarnings.length > 0" class="mb-4">
      <div
        class="mb-2 text-sm font-semibold text-amber-700 dark:text-amber-400"
      >
        Warnings ({{ validationWarnings.length }})
      </div>
      <ul class="list-inside list-disc space-y-1 text-sm text-amber-600">
        <li v-for="(warn, idx) in validationWarnings" :key="idx">
          <span v-if="warn.field" class="font-medium">{{ warn.field }}:</span>
          {{ warn.message }}
        </li>
      </ul>
    </div>

    <!-- Missing masters alert -->
    <div
      v-if="missingMasters.length > 0"
      class="mb-4 rounded-md bg-amber-50 p-3 dark:bg-amber-950"
    >
      <div class="text-sm font-medium text-amber-800 dark:text-amber-200">
        {{ missingMasters.length }} missing master record(s)
      </div>
      <ul class="mt-1 list-inside list-disc text-sm text-amber-700">
        <li v-for="(m, idx) in missingMasters" :key="idx">
          {{ m.doctype || m }}: {{ m.value || m.name || '' }}
        </li>
      </ul>
      <label class="mt-2 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          :checked="autoCreateMasters"
          @change="$emit('update:autoCreateMasters', $event.target.checked)"
        />
        Auto-create missing masters
      </label>
    </div>

    <!-- Action buttons -->
    <div class="flex items-center justify-end gap-3">
      <button
        class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
        :disabled="creating"
        @click="$emit('cancel')"
      >
        Cancel
      </button>
      <button
        class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="creating"
        @click="$emit('create')"
      >
        <span v-if="creating">Creating...</span>
        <span v-else>Create Draft</span>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  validationErrors: { type: Array, default: () => [] },
  validationWarnings: { type: Array, default: () => [] },
  missingMasters: { type: Array, default: () => [] },
  autoCreateMasters: { type: Boolean, default: false },
  creating: { type: Boolean, default: false },
})

defineEmits(['create', 'cancel', 'update:autoCreateMasters'])
</script>
