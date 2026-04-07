<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="grid h-full grid-cols-1 gap-4 lg:grid-cols-2">
    <!-- Left: Document preview -->
    <div
      class="flex flex-col rounded-lg border border-gray-200 dark:border-gray-700"
    >
      <div
        class="border-b border-gray-200 px-4 py-3 dark:border-gray-700"
      >
        <h3
          class="text-sm font-semibold text-gray-700 dark:text-gray-300"
        >
          Original Document
        </h3>
        <div v-if="fileName" class="text-xs text-gray-500">
          {{ fileName }}
        </div>
      </div>
      <div class="flex flex-1 items-center justify-center p-4">
        <DocumentThumbnail :file-url="fileUrl" :mime-type="mimeType" />
      </div>
    </div>

    <!-- Right: Extracted data -->
    <div
      class="flex flex-col rounded-lg border border-gray-200 dark:border-gray-700"
    >
      <div
        class="border-b border-gray-200 px-4 py-3 dark:border-gray-700"
      >
        <h3
          class="text-sm font-semibold text-gray-700 dark:text-gray-300"
        >
          Extracted Data
        </h3>
        <div v-if="confidence != null" class="text-xs text-gray-500">
          Confidence: {{ (confidence * 100).toFixed(1) }}%
        </div>
      </div>
      <div class="flex-1 overflow-y-auto p-4">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup>
import DocumentThumbnail from './DocumentThumbnail.vue'

defineProps({
  fileUrl: { type: String, default: '' },
  fileName: { type: String, default: '' },
  mimeType: { type: String, default: '' },
  confidence: { type: Number, default: null },
})
</script>
