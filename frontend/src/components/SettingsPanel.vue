<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="space-y-4">
    <!-- Target DocType -->
    <div>
      <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
        Target DocType
      </label>
      <select
        :value="targetDoctype"
        class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
        @change="$emit('update:targetDoctype', $event.target.value)"
      >
        <option
          v-for="dt in supportedDoctypes"
          :key="dt"
          :value="dt"
        >
          {{ dt }}
        </option>
      </select>
    </div>

    <!-- OCR Language -->
    <div>
      <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
        OCR Language
      </label>
      <select
        :value="language"
        class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
        @change="$emit('update:language', $event.target.value)"
      >
        <option
          v-for="(name, code) in ocrLanguages"
          :key="code"
          :value="code"
        >
          {{ name }} ({{ code }})
        </option>
      </select>
    </div>

    <!-- Company -->
    <div>
      <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
        Company
      </label>
      <input
        :value="company"
        type="text"
        placeholder="Default company"
        class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
        @input="$emit('update:company', $event.target.value)"
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  targetDoctype: { type: String, default: 'Purchase Invoice' },
  language: { type: String, default: 'en' },
  company: { type: String, default: '' },
  supportedDoctypes: { type: Array, default: () => [] },
  ocrLanguages: { type: Object, default: () => ({}) },
})

defineEmits(['update:targetDoctype', 'update:language', 'update:company'])
</script>
