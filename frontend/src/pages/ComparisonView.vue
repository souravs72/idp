<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="mx-auto max-w-6xl px-4 py-6">
    <!-- Header -->
    <div class="mb-6">
      <router-link
        to="/"
        class="text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400"
      >
        &larr; Back to Upload
      </router-link>
      <h1 class="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">
        Document Comparison
      </h1>
    </div>

    <!-- Comparison form (if no comparison yet) -->
    <div
      v-if="!comparison.comparison.value && !comparison.comparing.value"
      class="mb-6 space-y-4 rounded-lg border border-gray-200 p-6 dark:border-gray-700"
    >
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Compare DocType
          </label>
          <input
            v-model="compareDoctype"
            type="text"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
          />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Record Name
          </label>
          <input
            v-model="compareDocname"
            type="text"
            placeholder="e.g. PO-00042"
            class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
          />
        </div>
      </div>

      <div class="flex items-center gap-3">
        <button
          class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          :disabled="!fileUrl || !compareDocname"
          @click="runComparison"
        >
          Compare
        </button>
        <button
          class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
          :disabled="!fileUrl || comparison.finding.value"
          @click="autoMatch"
        >
          <span v-if="comparison.finding.value">Searching...</span>
          <span v-else>Auto-Find Match</span>
        </button>
      </div>

      <!-- Auto-match result -->
      <div
        v-if="comparison.matchedRecord.value"
        class="rounded-md bg-green-50 p-3 text-sm text-green-800 dark:bg-green-950 dark:text-green-200"
      >
        Found match:
        <strong>{{ comparison.matchedRecord.value.doctype }}</strong>
        {{ comparison.matchedRecord.value.docname }}
        <button
          class="ml-2 text-green-600 underline hover:text-green-800"
          @click="useMatch"
        >
          Use this
        </button>
      </div>
    </div>

    <!-- Processing status -->
    <ProcessingStatus
      v-if="comparison.comparing.value"
      message="Comparing document with record..."
      class="mb-4"
    />

    <!-- Error -->
    <div
      v-if="comparison.comparisonError.value"
      class="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
    >
      {{ comparison.comparisonError.value }}
    </div>

    <!-- Comparison results -->
    <ComparisonTable
      v-if="comparison.comparison.value"
      :matches="comparison.matches.value"
      :discrepancies="comparison.discrepancies.value"
      :items-comparison="comparison.itemsComparison.value"
      :summary="comparison.summary.value"
    />

    <!-- Actions after comparison -->
    <div
      v-if="comparison.comparison.value"
      class="mt-6 flex items-center justify-end gap-3"
    >
      <button
        class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300"
        @click="router.push('/')"
      >
        Dismiss
      </button>
      <button
        class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        @click="acceptAndCreate"
      >
        Accept &amp; Create
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ComparisonTable from '@/components/ComparisonTable.vue'
import ProcessingStatus from '@/components/ProcessingStatus.vue'
import { useComparison } from '@/composables/useComparison'

const route = useRoute()
const router = useRouter()
const comparison = useComparison()

const fileUrl = ref(route.query.fileUrl || '')
const compareDoctype = ref(route.query.doctype || 'Purchase Order')
const compareDocname = ref(route.query.docname || '')
const company = ref(route.query.company || '')
const language = ref(route.query.language || 'en')

onMounted(() => {
  // If docname is provided, auto-compare
  if (fileUrl.value && compareDocname.value) {
    runComparison()
  }
})

async function runComparison() {
  await comparison.compare({
    fileUrl: fileUrl.value,
    compareDoctype: compareDoctype.value,
    compareDocname: compareDocname.value,
    company: company.value,
    language: language.value,
  })
}

async function autoMatch() {
  await comparison.findMatch({
    fileUrl: fileUrl.value,
    targetDoctype: compareDoctype.value,
    company: company.value,
    language: language.value,
  })
}

function useMatch() {
  if (comparison.matchedRecord.value) {
    compareDoctype.value = comparison.matchedRecord.value.doctype
    compareDocname.value = comparison.matchedRecord.value.docname
    runComparison()
  }
}

function acceptAndCreate() {
  router.push({
    name: 'ExtractionReview',
    query: {
      fileUrl: fileUrl.value,
      doctype: compareDoctype.value,
      company: company.value,
      language: language.value,
    },
  })
}
</script>
