<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div
    class="relative rounded-lg border-2 border-dashed p-8 text-center transition-colors"
    :class="[
      isDragging
        ? 'border-blue-500 bg-blue-50 dark:bg-blue-950'
        : hasFile
          ? 'border-green-400 bg-green-50 dark:bg-green-950'
          : 'border-gray-300 hover:border-gray-400 dark:border-gray-600',
    ]"
    @dragenter="onDragEnter"
    @dragleave="onDragLeave"
    @dragover="onDragOver"
    @drop="onDrop"
    @click="openFileDialog"
  >
    <input
      ref="fileInput"
      type="file"
      class="hidden"
      :accept="acceptFormats"
      @change="onFileSelect"
    />

    <div v-if="hasFile" class="space-y-2">
      <div class="text-lg font-medium text-green-700 dark:text-green-300">
        {{ fileName }}
      </div>
      <div class="text-sm text-gray-500">
        {{ formattedSize }} &middot; {{ mimeType }}
      </div>
      <button
        class="mt-2 text-sm text-blue-600 underline hover:text-blue-800"
        @click.stop="reset"
      >
        Choose a different file
      </button>
    </div>

    <div v-else class="space-y-3">
      <div class="mx-auto h-12 w-12 text-gray-400">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          stroke-width="1.5"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12-3-3m0 0-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
          />
        </svg>
      </div>
      <div class="text-lg font-medium text-gray-700 dark:text-gray-300">
        Drop files here or click to upload
      </div>
      <div class="text-sm text-gray-500">
        PDF, Images, Excel, CSV, Word (max {{ maxSizeMb }} MB)
      </div>
    </div>

    <div v-if="error" class="mt-3 text-sm text-red-600">
      {{ error }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { formatFileSize } from '@/utils/formatters'

const props = defineProps({
  fileName: { type: String, default: '' },
  mimeType: { type: String, default: '' },
  fileSize: { type: Number, default: 0 },
  hasFile: { type: Boolean, default: false },
  isDragging: { type: Boolean, default: false },
  error: { type: String, default: null },
  acceptFormats: {
    type: String,
    default:
      '.pdf,.png,.jpg,.jpeg,.webp,.tiff,.tif,.xlsx,.xls,.csv,.docx',
  },
  maxSizeMb: { type: Number, default: 25 },
})

const emit = defineEmits([
  'select',
  'reset',
  'dragenter',
  'dragleave',
  'dragover',
  'drop',
])

const fileInput = ref(null)

const formattedSize = computed(() => formatFileSize(props.fileSize))

function openFileDialog() {
  if (!props.hasFile) {
    fileInput.value?.click()
  }
}

function onFileSelect(e) {
  const files = e.target.files
  if (files && files.length > 0) {
    emit('select', files[0])
  }
}

function onDragEnter(e) {
  emit('dragenter', e)
}
function onDragLeave(e) {
  emit('dragleave', e)
}
function onDragOver(e) {
  emit('dragover', e)
}
function onDrop(e) {
  emit('drop', e)
}

function reset() {
  if (fileInput.value) fileInput.value.value = ''
  emit('reset')
}
</script>
