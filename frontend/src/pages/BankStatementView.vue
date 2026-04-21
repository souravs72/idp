<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="mx-auto max-w-6xl px-4 py-6">
    <div class="mb-6">
      <router-link
        to="/"
        class="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400"
      >
        &larr; Back to Upload
      </router-link>
      <h1 class="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">
        Bank Statement Reconciliation
      </h1>
      <p class="mt-1 text-sm text-gray-500">
        Upload a bank statement PDF/image, parse its transactions, and reconcile
        them against ERPNext Payment Entries.
      </p>
    </div>

    <!-- Step 1: File upload + extract -->
    <div
      v-if="!reconciler.statement.value"
      class="mb-6 rounded-lg border border-gray-200 p-6 dark:border-gray-700"
    >
      <FileDropzone
        :file-name="fileUpload.fileName.value"
        :mime-type="fileUpload.mimeType.value"
        :file-size="fileUpload.fileSize.value"
        :has-file="fileUpload.hasFile.value"
        :is-dragging="fileUpload.isDragging.value"
        :error="fileUpload.uploadError.value"
        :max-size-mb="settings.settings.value?.max_file_size_mb || 25"
        class="mb-4"
        @select="fileUpload.selectFile"
        @reset="fileUpload.reset"
        @dragenter="fileUpload.onDragEnter"
        @dragleave="fileUpload.onDragLeave"
        @dragover="fileUpload.onDragOver"
        @drop="fileUpload.onDrop"
      />

      <div class="flex items-center gap-3">
        <div class="flex-1">
          <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            OCR Language
          </label>
          <input
            v-model="language"
            type="text"
            class="w-48 rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
          />
        </div>
        <button
          class="rounded-md bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="!fileUpload.hasFile.value || reconciler.extracting.value"
          @click="runExtract"
        >
          <span v-if="reconciler.extracting.value">Parsing…</span>
          <span v-else>Parse Bank Statement</span>
        </button>
      </div>
    </div>

    <!-- Processing status -->
    <ProcessingStatus
      v-if="reconciler.extracting.value || fileUpload.uploading.value"
      :message="
        fileUpload.uploading.value
          ? 'Uploading file...'
          : 'Parsing bank statement...'
      "
      class="mb-4"
    />

    <!-- Error display -->
    <div
      v-if="reconciler.error.value"
      class="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
    >
      {{ reconciler.error.value }}
    </div>

    <!-- Step 2: Parsed statement + reconciliation -->
    <BankReconciliation
      v-if="reconciler.statement.value"
      :statement="reconciler.statement.value"
      :reconciliation="reconciler.reconciliation.value"
      :reconciling="reconciler.reconciling.value"
      :bank-account="bankAccount"
      :company="company"
      @reconcile="runReconcile"
    />

    <!-- Reset -->
    <div
      v-if="reconciler.statement.value"
      class="mt-6 flex justify-end"
    >
      <button
        class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
        @click="resetAll"
      >
        Start Over
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import FileDropzone from '@/components/FileDropzone.vue'
import ProcessingStatus from '@/components/ProcessingStatus.vue'
import BankReconciliation from '@/components/BankReconciliation.vue'
import { useSettings } from '@/composables/useSettings'
import { useFileUpload } from '@/composables/useFileUpload'
import { useBankReconciliation } from '@/composables/useBankReconciliation'

const settings = useSettings()
const fileUpload = useFileUpload()
const reconciler = useBankReconciliation()

const language = ref('en')
const bankAccount = ref('')
const company = ref('')

onMounted(async () => {
  await settings.load()
  language.value = settings.settings.value?.default_ocr_language || 'en'
  company.value = settings.settings.value?.default_company || ''
})

async function runExtract() {
  if (!fileUpload.fileUrl.value) {
    const uploadResult = await fileUpload.upload()
    if (!uploadResult) return
  }
  await reconciler.extract({
    fileUrl: fileUpload.fileUrl.value,
    language: language.value,
  })
}

async function runReconcile(payload) {
  bankAccount.value = payload.bankAccount
  company.value = payload.company
  await reconciler.reconcile({
    bankAccount: payload.bankAccount,
    company: payload.company,
  })
}

function resetAll() {
  reconciler.reset()
  fileUpload.reset()
}
</script>
