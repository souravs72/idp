<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div
    class="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950"
  >
    <!-- Spinner -->
    <div class="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />

    <div class="flex-1">
      <div class="text-sm font-medium text-blue-800 dark:text-blue-200">
        {{ message }}
      </div>
      <div v-if="stage" class="mt-1 text-xs text-blue-600 dark:text-blue-400">
        Stage: {{ stage }}
      </div>
    </div>

    <div
      v-if="processingTimeMs > 0"
      class="text-xs text-blue-500"
    >
      {{ (processingTimeMs / 1000).toFixed(1) }}s
    </div>
  </div>
</template>

<script setup>
defineProps({
  message: { type: String, default: 'Processing...' },
  stage: { type: String, default: '' },
  processingTimeMs: { type: Number, default: 0 },
})
</script>
