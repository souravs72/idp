<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="mx-auto max-w-7xl px-4 py-6">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div>
        <router-link
          to="/"
          class="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400"
        >
          &larr; Back to Upload
        </router-link>
        <h1 class="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">
          Review Extraction: {{ doctype }}
        </h1>
        <div
          v-if="extraction.processingTimeMs.value"
          class="text-xs text-gray-500"
        >
          Processed in {{ extraction.processingTimeMs.value }}ms
        </div>
      </div>
    </div>

    <!-- Side-by-side preview -->
    <ExtractionPreview
      :file-url="fileUrl"
      :file-name="fileName"
      :mime-type="mimeType"
      :confidence="extraction.confidence.value"
      class="mb-6"
    >
      <ExtractionForm
        :header="extraction.extractedData.value?.header || {}"
        :items="extraction.extractedData.value?.items || []"
        :unmapped-fields="extraction.unmappedFields.value"
        @update-header="extraction.updateHeaderField"
        @update-item="extraction.updateItemField"
      />
    </ExtractionPreview>

    <!-- Confirmation card -->
    <ConfirmationCard
      :validation-errors="extraction.validationErrors.value"
      :validation-warnings="extraction.validationWarnings.value"
      :missing-masters="extraction.missingMasters.value"
      :auto-create-masters="autoCreateMasters"
      :creating="extraction.creating.value"
      @update:auto-create-masters="autoCreateMasters = $event"
      @cancel="router.push('/')"
      @create="handleCreate"
    />

    <!-- Missing masters dialog -->
    <MissingMastersDialog
      v-model="showMissingMasters"
      :missing-masters="extraction.missingMasters.value"
      @create-masters="handleCreateWithMasters"
    />

    <!-- Creation result -->
    <div
      v-if="extraction.creationResult.value"
      class="mt-4 rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950"
    >
      <div class="text-sm font-medium text-green-800 dark:text-green-200">
        Created {{ extraction.creationResult.value.doctype }}:
        <a
          :href="extraction.creationResult.value.url"
          target="_blank"
          class="underline"
        >
          {{ extraction.creationResult.value.name }}
        </a>
      </div>
    </div>

    <!-- Creation error -->
    <div
      v-if="extraction.creationError.value"
      class="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
    >
      {{ extraction.creationError.value }}
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExtractionPreview from '@/components/ExtractionPreview.vue'
import ExtractionForm from '@/components/ExtractionForm.vue'
import ConfirmationCard from '@/components/ConfirmationCard.vue'
import MissingMastersDialog from '@/components/MissingMastersDialog.vue'
import { useExtraction } from '@/composables/useExtraction'

const route = useRoute()
const router = useRouter()
const extraction = useExtraction()

const fileUrl = ref(route.query.fileUrl || '')
const fileName = ref(route.query.fileName || '')
const mimeType = ref(route.query.mimeType || '')
const doctype = ref(route.query.doctype || 'Purchase Invoice')
const company = ref(route.query.company || '')
const autoCreateMasters = ref(false)
const showMissingMasters = ref(false)

onMounted(async () => {
  // If no extraction data yet, extract now
  if (!extraction.extractedData.value && fileUrl.value) {
    await extraction.extract({
      fileUrl: fileUrl.value,
      targetDoctype: doctype.value,
      company: company.value,
      language: route.query.language || 'en',
    })
  }

  // Check for missing masters
  if (extraction.extractedData.value) {
    await extraction.checkMissingMasters({
      targetDoctype: doctype.value,
      company: company.value,
    })
  }
})

async function handleCreate() {
  // If there are missing masters and auto-create is off, show dialog
  if (extraction.missingMasters.value.length > 0 && !autoCreateMasters.value) {
    showMissingMasters.value = true
    return
  }

  await extraction.create({
    targetDoctype: doctype.value,
    company: company.value,
    createMissingMasters: autoCreateMasters.value,
  })
}

async function handleCreateWithMasters() {
  showMissingMasters.value = false
  autoCreateMasters.value = true
  await extraction.create({
    targetDoctype: doctype.value,
    company: company.value,
    createMissingMasters: true,
  })
}
</script>
