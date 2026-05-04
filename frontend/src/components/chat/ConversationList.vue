<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <aside
    class="flex h-full w-72 flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-950"
  >
    <header
      class="flex items-center justify-between border-b border-gray-200 p-3 dark:border-gray-700"
    >
      <div class="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Conversations
      </div>
      <button
        type="button"
        class="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="starting"
        @click="$emit('new')"
      >
        {{ starting ? 'Starting…' : '+ New' }}
      </button>
    </header>

    <div class="flex items-center gap-2 border-b border-gray-200 px-3 py-2 text-xs dark:border-gray-700">
      <button
        v-for="opt in statusOptions"
        :key="opt.value"
        class="rounded px-2 py-0.5"
        :class="
          currentStatus === opt.value
            ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
            : 'text-gray-600 hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800'
        "
        @click="$emit('status-change', opt.value)"
      >
        {{ opt.label }}
      </button>
    </div>

    <div class="flex-1 overflow-y-auto">
      <div
        v-if="loading && !sessions.length"
        class="p-4 text-center text-xs text-gray-500"
      >
        Loading…
      </div>
      <div
        v-else-if="!sessions.length"
        class="p-4 text-center text-xs text-gray-500"
      >
        No conversations yet. Start a new one.
      </div>
      <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
        <li
          v-for="row in sessions"
          :key="row.name"
          class="cursor-pointer px-3 py-2 hover:bg-blue-50 dark:hover:bg-gray-800"
          :class="
            row.name === activeId
              ? 'bg-blue-100 dark:bg-blue-950'
              : ''
          "
          @click="$emit('select', row.name)"
        >
          <div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {{ row.title || `Conversation ${row.name}` }}
          </div>
          <div class="mt-0.5 flex items-center justify-between text-[11px] text-gray-500">
            <span>{{ formatTime(row.last_message_on || row.modified) }}</span>
            <span v-if="row.message_count">{{ row.message_count }} msg</span>
          </div>
          <div
            v-if="row.target_doctype || row.llm_model"
            class="mt-0.5 flex items-center gap-1 text-[10px] text-gray-400"
          >
            <span v-if="row.target_doctype">{{ row.target_doctype }}</span>
            <span v-if="row.target_doctype && row.llm_model">·</span>
            <span v-if="row.llm_model">{{ row.llm_model }}</span>
          </div>
        </li>
      </ul>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  loading: { type: Boolean, default: false },
  currentStatus: { type: String, default: 'Active' },
  starting: { type: Boolean, default: false },
})

defineEmits(['select', 'new', 'status-change'])

const statusOptions = [
  { value: 'Active', label: 'Active' },
  { value: 'Archived', label: 'Archived' },
]

function formatTime(value) {
  if (!value) return ''
  try {
    const d = new Date(value)
    const now = new Date()
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString()
  } catch (_) {
    return value
  }
}
</script>
