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
        <!-- Phase 29 — confidence band dot replaces the numeric % when
             ``show_confidence_dots`` is on; the numeric stays as a
             hover tooltip on the dot itself for power users.  We
             default to the dot view unless the page explicitly opts
             out via ``forceNumeric``. -->
        <div v-if="confidence != null" class="flex items-center gap-1.5 text-xs text-gray-500">
          <template v-if="!forceNumeric">
            <ConfidenceDot :band="band" :value="confidence" />
            <span class="capitalize">{{ bandLabel }}</span>
          </template>
          <template v-else>
            Confidence: {{ (confidence * 100).toFixed(1) }}%
          </template>
        </div>
      </div>
      <div class="flex-1 overflow-y-auto p-4">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import DocumentThumbnail from './DocumentThumbnail.vue'
import ConfidenceDot from './chat/ConfidenceDot.vue'

const props = defineProps({
  fileUrl: { type: String, default: '' },
  fileName: { type: String, default: '' },
  mimeType: { type: String, default: '' },
  confidence: { type: Number, default: null },
  // Phase 29 — escape hatch for legacy callers that prefer the
  // numeric display.  Off by default to match the roadmap rollout.
  forceNumeric: { type: Boolean, default: false },
})

// Local fallback for the band when the caller doesn't precompute it.
// Mirrors the server-side defaults in idp/llm/confidence.py.
const band = computed(() => {
  const v = props.confidence
  if (v == null || !Number.isFinite(v)) return 'red'
  if (v >= 0.75) return 'green'
  if (v >= 0.55) return 'amber'
  return 'red'
})

const bandLabel = computed(() => {
  if (band.value === 'green') return 'High'
  if (band.value === 'amber') return 'Medium'
  return 'Low'
})
</script>
