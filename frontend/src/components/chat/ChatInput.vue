<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <form
    class="border-t border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-900"
    @submit.prevent="onSubmit"
  >
    <!-- Pending attachments -->
    <div v-if="pending.length" class="mb-2 flex flex-wrap gap-2">
      <span
        v-for="(att, idx) in pending"
        :key="att.file_url || idx"
        class="inline-flex items-center gap-2 rounded-full border border-gray-300 bg-gray-100 px-3 py-1 text-xs dark:border-gray-700 dark:bg-gray-800"
      >
        <span aria-hidden="true">📎</span>
        <span class="max-w-[160px] truncate">
          {{ att.file_name || att.file_url }}
        </span>
        <button
          type="button"
          class="text-gray-500 hover:text-red-600"
          aria-label="Remove attachment"
          @click="remove(idx)"
        >
          ×
        </button>
      </span>
    </div>

    <div class="flex items-end gap-2">
      <label
        class="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded border border-gray-300 text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        :class="{ 'opacity-50': uploading }"
      >
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          multiple
          :disabled="uploading || disabled"
          @change="onFileChange"
        />
        <span aria-hidden="true">📎</span>
      </label>

      <textarea
        v-model="draft"
        :disabled="disabled"
        rows="2"
        class="flex-1 resize-none rounded border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100"
        :placeholder="placeholder"
        @keydown="onKeydown"
      />

      <button
        type="submit"
        :disabled="!canSubmit"
        class="h-9 rounded bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {{ disabled ? 'Working…' : 'Send' }}
      </button>
    </div>

    <div
      v-if="lastError"
      class="mt-2 text-xs text-red-700 dark:text-red-400"
    >
      {{ lastError }}
    </div>
  </form>
</template>

<script setup>
import { computed, ref } from 'vue'
import { uploadDocument } from '@/utils/api'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  placeholder: {
    type: String,
    default: 'Ask something or attach a document…',
  },
})

const emit = defineEmits(['send'])

const draft = ref('')
const pending = ref([])
const uploading = ref(false)
const lastError = ref(null)
const fileInput = ref(null)

const canSubmit = computed(() => {
  if (props.disabled) return false
  if (uploading.value) return false
  if (draft.value.trim().length) return true
  if (pending.value.length) return true
  return false
})

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSubmit()
  }
}

async function onFileChange(event) {
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  uploading.value = true
  lastError.value = null
  try {
    for (const file of files) {
      const res = await uploadDocument(file)
      // frappeRequest returns the unwrapped message; raw fetch gives { message: ... }
      const data = res?.message || res?.data || res
      if (data?.file_url) {
        pending.value.push({
          file_url: data.file_url,
          file_id: data.file_id || data.name,
          file_name: data.file_name || file.name,
          mime_type: data.mime_type || file.type,
        })
      } else if (data?.error) {
        lastError.value = String(data.error)
      }
    }
  } catch (err) {
    lastError.value = err?.message || String(err)
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function remove(idx) {
  pending.value.splice(idx, 1)
}

function onSubmit() {
  if (!canSubmit.value) return
  const payload = {
    content: draft.value.trim(),
    attachments: [...pending.value],
  }
  draft.value = ''
  pending.value = []
  emit('send', payload)
}
</script>
