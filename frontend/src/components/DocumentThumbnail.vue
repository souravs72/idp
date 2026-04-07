<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="flex flex-col items-center justify-center text-center">
    <!-- Image preview -->
    <img
      v-if="isImage"
      :src="fileUrl"
      :alt="fileUrl"
      class="max-h-96 max-w-full rounded-lg object-contain shadow-sm"
    />

    <!-- PDF embed -->
    <iframe
      v-else-if="isPdf"
      :src="fileUrl"
      class="h-96 w-full rounded-lg border border-gray-200 dark:border-gray-700"
      title="Document preview"
    />

    <!-- Generic file icon -->
    <div v-else class="space-y-2 p-8 text-gray-400">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="1.5"
        stroke="currentColor"
        class="mx-auto h-16 w-16"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
        />
      </svg>
      <div class="text-sm">
        {{ fileExtension.toUpperCase() }} file
      </div>
      <div class="text-xs">Preview not available</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  fileUrl: { type: String, default: '' },
  mimeType: { type: String, default: '' },
})

const isImage = computed(() => props.mimeType?.startsWith('image/'))

const isPdf = computed(() => props.mimeType === 'application/pdf')

const fileExtension = computed(() => {
  if (!props.fileUrl) return ''
  const parts = props.fileUrl.split('.')
  return parts.length > 1 ? parts[parts.length - 1] : ''
})
</script>
