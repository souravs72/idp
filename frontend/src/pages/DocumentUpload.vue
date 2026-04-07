<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="mx-auto max-w-4xl px-4 py-8">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-gray-100">
          Intelligent Document Processing
        </h1>
        <p class="mt-1 text-sm text-gray-500">
          Upload a document to extract structured data and create ERPNext records.
        </p>
      </div>
      <router-link
        to="/history"
        class="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400"
      >
        History
      </router-link>
    </div>

    <!-- File dropzone -->
    <FileDropzone
      :file-name="fileUpload.fileName.value"
      :mime-type="fileUpload.mimeType.value"
      :file-size="fileUpload.fileSize.value"
      :has-file="fileUpload.hasFile.value"
      :is-dragging="fileUpload.isDragging.value"
      :error="fileUpload.uploadError.value"
      :max-size-mb="settings.settings.value?.max_file_size_mb || 25"
      class="mb-6"
      @select="fileUpload.selectFile"
      @reset="fileUpload.reset"
      @dragenter="fileUpload.onDragEnter"
      @dragleave="fileUpload.onDragLeave"
      @dragover="fileUpload.onDragOver"
      @drop="fileUpload.onDrop"
    />

    <!-- Settings panel -->
    <SettingsPanel
      v-model:target-doctype="targetDoctype"
      v-model:language="language"
      v-model:company="company"
      :supported-doctypes="settings.getSupportedDoctypes()"
      :ocr-languages="settings.getOcrLanguages()"
      class="mb-6"
    />

    <!-- Extract button -->
    <div class="flex items-center gap-3">
      <button
        class="rounded-md bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="!fileUpload.hasFile.value || extraction.extracting.value"
        @click="startExtraction"
      >
        <span v-if="extraction.extracting.value">Extracting...</span>
        <span v-else>Extract Document</span>
      </button>

      <button
        v-if="fileUpload.hasFile.value && settings.settings.value?.features?.comparison"
        class="rounded-md border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
        :disabled="extraction.extracting.value"
        @click="startComparison"
      >
        Compare with Record
      </button>
    </div>

    <!-- Processing status -->
    <ProcessingStatus
      v-if="extraction.extracting.value || fileUpload.uploading.value"
      :message="fileUpload.uploading.value ? 'Uploading file...' : 'Extracting data...'"
      class="mt-4"
    />

    <!-- Error display -->
    <div
      v-if="extraction.extractionError.value"
      class="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
    >
      {{ extraction.extractionError.value }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import FileDropzone from '@/components/FileDropzone.vue'
import SettingsPanel from '@/components/SettingsPanel.vue'
import ProcessingStatus from '@/components/ProcessingStatus.vue'
import { useSettings } from '@/composables/useSettings'
import { useFileUpload } from '@/composables/useFileUpload'
import { useExtraction } from '@/composables/useExtraction'

const router = useRouter()
const settings = useSettings()
const fileUpload = useFileUpload()
const extraction = useExtraction()

const targetDoctype = ref('Purchase Invoice')
const language = ref('en')
const company = ref('')

onMounted(async () => {
  await settings.load()
  targetDoctype.value =
    settings.settings.value?.default_target_doctype || 'Purchase Invoice'
  language.value =
    settings.settings.value?.default_ocr_language || 'en'
})

async function startExtraction() {
  // Upload file first if needed
  if (!fileUpload.fileUrl.value) {
    const uploadResult = await fileUpload.upload()
    if (!uploadResult) return
  }

  // Run extraction
  const result = await extraction.extract({
    fileUrl: fileUpload.fileUrl.value,
    targetDoctype: targetDoctype.value,
    company: company.value,
    language: language.value,
  })

  if (result) {
    // Navigate to review page
    router.push({
      name: 'ExtractionReview',
      query: {
        fileUrl: fileUpload.fileUrl.value,
        fileName: fileUpload.fileName.value,
        mimeType: fileUpload.mimeType.value,
        doctype: targetDoctype.value,
        company: company.value,
      },
    })
  }
}

function startComparison() {
  router.push({
    name: 'ComparisonView',
    query: {
      fileUrl: fileUpload.fileUrl.value,
      fileName: fileUpload.fileName.value,
      doctype: targetDoctype.value,
      company: company.value,
      language: language.value,
    },
  })
}
</script>
