<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 29 — Provenance & Confidence Surface.

  Renders a single coloured dot (green / amber / red) with an
  accessible label.  Hover / long-press surfaces the underlying
  numeric for power users.

  Falls back to a neutral grey dot when ``band`` is missing or
  unrecognised so the UI never breaks on legacy / partial payloads.
-->

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // Discrete band emitted by the backend (idp/llm/confidence.py).
  band: {
    type: String,
    default: null,
    validator: (v) => v == null || ['green', 'amber', 'red'].includes(v),
  },
  // Raw numeric (0-1) — used only for the hover tooltip.  Optional.
  value: { type: Number, default: null },
  // Visual size variant.
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
})

const LABELS = {
  green: 'High confidence',
  amber: 'Medium confidence',
  red: 'Low confidence',
}

const SIZE_PX = { sm: 8, md: 10, lg: 12 }

const ariaLabel = computed(() => {
  const base = LABELS[props.band] || 'Confidence not available'
  if (props.value != null && Number.isFinite(props.value)) {
    return `${base} (${(props.value * 100).toFixed(0)}%)`
  }
  return base
})

const tooltip = computed(() => {
  if (props.value != null && Number.isFinite(props.value)) {
    return `${(props.value * 100).toFixed(1)}%`
  }
  return LABELS[props.band] || 'No confidence recorded'
})

const dotClass = computed(() => {
  switch (props.band) {
    case 'green':
      return 'bg-emerald-500'
    case 'amber':
      return 'bg-amber-500'
    case 'red':
      return 'bg-red-500'
    default:
      return 'bg-gray-300 dark:bg-gray-600'
  }
})

const dim = computed(() => `${SIZE_PX[props.size]}px`)
</script>

<template>
  <span
    role="img"
    :aria-label="ariaLabel"
    :title="tooltip"
    class="inline-block flex-none rounded-full align-middle"
    :class="dotClass"
    :style="{ width: dim, height: dim }"
  />
</template>
