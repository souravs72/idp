<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <span
    class="inline-flex items-center rounded-full font-medium"
    :class="[sizeClasses, colorClasses]"
  >
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: 'match' },
  size: { type: String, default: 'md' },
})

const sizeClasses = computed(() =>
  props.size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs',
)

const colorClasses = computed(() => {
  switch (props.status) {
    case 'match':
      return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
    case 'mismatch':
      return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
    case 'partial_match':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'
    case 'missing':
    case 'extra_in_document':
    case 'extra_in_record':
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
    default:
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
  }
})

const label = computed(() => {
  switch (props.status) {
    case 'match':
      return 'Match'
    case 'mismatch':
      return 'Diff'
    case 'partial_match':
      return 'Partial'
    case 'missing':
      return 'Missing'
    case 'extra_in_document':
      return 'Extra (Doc)'
    case 'extra_in_record':
      return 'Extra (Rec)'
    default:
      return props.status
  }
})
</script>
