<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 29 — Provenance & Confidence Surface.

  Right-hand collapsible PDF preview with bbox highlight.  Lazy-loads
  ``pdfjs-dist`` on the first ``focus`` so the bundle cost is only paid
  once a user actually clicks a field with a source region.

  Inputs:
    - ``fileUrl`` : absolute / relative URL to the source PDF
    - ``highlight``: ``{ page, bbox: [x0, y0, x1, y1] }`` or null

  Bbox coordinates are PDF-space pixels as reported by PaddleOCR (or
  the Ollama-vision fallback when bboxes are available).  We convert
  them to canvas-space via the same scale factor used to render the
  page.
-->

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  fileUrl: { type: String, default: '' },
  highlight: { type: Object, default: null }, // { page, bbox }
  // Width budget for the rendered canvas.  Height follows aspect.
  width: { type: Number, default: 480 },
})

const canvasEl = ref(null)
const containerEl = ref(null)
const loading = ref(false)
const error = ref(null)
const rendered = ref(false)
// Track the most recent render so we can position the overlay rectangle.
const lastScale = ref(1)
const pageHeightPx = ref(0)

// Lazy module handle — only resolves on first call to ``ensurePdfjs``.
let _pdfjs = null

async function ensurePdfjs() {
  if (_pdfjs) return _pdfjs
  // Dynamic import keeps the ~1.5 MB worker bundle out of the main
  // chunk.  The worker URL is resolved via Vite's ?url query suffix.
  const pdfjs = await import('pdfjs-dist/build/pdf.mjs')
  try {
    const worker = await import('pdfjs-dist/build/pdf.worker.mjs?url')
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
  } catch (_e) {
    // Fall back to inline worker — slower but functional in builds
    // where the worker URL isn't resolvable.
  }
  _pdfjs = pdfjs
  return pdfjs
}

async function renderHighlight() {
  if (!props.fileUrl || !props.highlight || !canvasEl.value) return
  const page = Number(props.highlight.page || 1)
  if (!page || page < 1) return
  loading.value = true
  error.value = null
  try {
    const pdfjs = await ensurePdfjs()
    const doc = await pdfjs.getDocument(props.fileUrl).promise
    const pdfPage = await doc.getPage(page)
    const viewport = pdfPage.getViewport({ scale: 1 })
    const scale = props.width / viewport.width
    const scaled = pdfPage.getViewport({ scale })

    const canvas = canvasEl.value
    canvas.width = scaled.width
    canvas.height = scaled.height
    pageHeightPx.value = scaled.height
    lastScale.value = scale

    const ctx = canvas.getContext('2d')
    await pdfPage.render({ canvasContext: ctx, viewport: scaled }).promise
    rendered.value = true
  } catch (e) {
    error.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

// Compute the overlay rectangle in canvas-space.  PaddleOCR bboxes
// are reported in PDF coordinates (origin top-left for image OCR);
// we trust the upstream convention and pin to the canvas.
const overlayStyle = computed(() => {
  const h = props.highlight
  if (!h || !Array.isArray(h.bbox) || h.bbox.length !== 4) return null
  const [x0, y0, x1, y1] = h.bbox
  const s = lastScale.value || 1
  return {
    left: `${x0 * s}px`,
    top: `${y0 * s}px`,
    width: `${Math.max(0, x1 - x0) * s}px`,
    height: `${Math.max(0, y1 - y0) * s}px`,
  }
})

watch(
  () => [props.fileUrl, props.highlight?.page, JSON.stringify(props.highlight?.bbox || [])],
  () => {
    renderHighlight()
  },
  { immediate: true },
)
</script>

<template>
  <div
    ref="containerEl"
    class="flex h-full flex-col overflow-auto rounded border border-gray-200 bg-white p-2 dark:border-gray-700 dark:bg-gray-900"
  >
    <div
      v-if="!fileUrl"
      class="m-auto text-xs text-gray-500 dark:text-gray-400"
    >
      Select a field with a source region to preview the PDF.
    </div>
    <div v-else-if="loading" class="m-auto text-xs text-gray-500">
      Loading PDF…
    </div>
    <div v-else-if="error" class="m-auto text-xs text-red-600">
      Couldn't render PDF: {{ error }}
    </div>
    <div class="relative inline-block">
      <canvas ref="canvasEl" class="block max-w-full" />
      <div
        v-if="overlayStyle && rendered"
        class="pointer-events-none absolute rounded border-2 border-amber-500 bg-amber-300/20"
        :style="overlayStyle"
      />
    </div>
    <div
      v-if="highlight && !overlayStyle"
      class="mt-1 text-[10px] text-gray-400"
    >
      No source region recorded for this field.
    </div>
  </div>
</template>
