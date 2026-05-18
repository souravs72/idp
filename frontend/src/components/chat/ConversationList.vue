<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <aside
    class="flex h-full flex-col border-r border-gray-200 bg-gray-50 transition-[width] duration-150 ease-out dark:border-gray-700 dark:bg-gray-950"
    :class="collapsed ? 'w-12' : 'w-72'"
  >
    <!-- ============================================================ -->
    <!-- Header: collapse toggle + (when expanded) title and + New      -->
    <!-- ============================================================ -->
    <header
      class="flex items-center border-b border-gray-200 dark:border-gray-700"
      :class="collapsed ? 'justify-center p-2' : 'justify-between p-3 gap-2'"
    >
      <button
        type="button"
        class="rounded p-1 text-gray-500 hover:bg-gray-200 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
        :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="$emit('toggle')"
      >
        <span class="text-base leading-none">{{ collapsed ? '»' : '«' }}</span>
      </button>

      <template v-if="!collapsed">
        <div class="flex-1 truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
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
      </template>
    </header>

    <!-- When collapsed, render just a compact +New affordance and nothing else -->
    <template v-if="collapsed">
      <button
        type="button"
        class="m-2 rounded bg-blue-600 px-1 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="starting"
        title="New conversation"
        @click="$emit('new')"
      >
        +
      </button>
    </template>

    <template v-else>
      <!-- ============================================================ -->
      <!-- Status pills (Active / Archived)                              -->
      <!-- ============================================================ -->
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
          @click="onStatusChange(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>

      <!-- ============================================================ -->
      <!-- Search box + filter chips (gated by enable_sidebar_search)    -->
      <!-- ============================================================ -->
      <div
        v-if="searchEnabled"
        class="space-y-2 border-b border-gray-200 px-3 py-2 dark:border-gray-700"
      >
        <div class="relative">
          <input
            v-model="query"
            type="text"
            placeholder="Search conversations…"
            class="w-full rounded border border-gray-300 bg-white px-2 py-1 pr-6 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
            @input="onSearchInput"
          />
          <button
            v-if="query"
            type="button"
            class="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            title="Clear"
            @click="clearSearch"
          >
            ×
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-1 text-[11px]">
          <button
            v-for="opt in dateOptions"
            :key="opt.value"
            type="button"
            class="rounded-full px-2 py-0.5"
            :class="
              dateRange === opt.value
                ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'
            "
            @click="setDateRange(opt.value)"
          >
            {{ opt.label }}
          </button>

          <label
            class="ml-1 inline-flex cursor-pointer items-center gap-1 rounded-full px-2 py-0.5"
            :class="
              hasAttachments
                ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'
            "
          >
            <input
              v-model="hasAttachments"
              type="checkbox"
              class="hidden"
              @change="emitSearch"
            />
            📎 attached
          </label>
        </div>
      </div>

      <!-- ============================================================ -->
      <!-- Session list                                                  -->
      <!-- ============================================================ -->
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
          {{ query ? 'No matches.' : 'No conversations yet. Start a new one.' }}
        </div>
        <ul v-else class="divide-y divide-gray-100 dark:divide-gray-800">
          <li
            v-for="row in sessions"
            :key="row.name"
            class="group relative cursor-pointer px-3 py-2 pr-8 hover:bg-blue-50 dark:hover:bg-gray-800"
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

            <button
              v-if="deleteEnabled"
              type="button"
              class="absolute right-2 top-2 rounded p-1 text-gray-400 opacity-60 hover:bg-red-100 hover:text-red-600 hover:opacity-100 group-hover:opacity-100 dark:hover:bg-red-900 dark:hover:text-red-300"
              title="Delete conversation"
              aria-label="Delete conversation"
              @click.stop="onDelete(row)"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                class="h-3.5 w-3.5"
                aria-hidden="true"
              >
                <path
                  fill-rule="evenodd"
                  d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z"
                  clip-rule="evenodd"
                />
              </svg>
            </button>
          </li>
        </ul>
      </div>
    </template>
  </aside>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  loading: { type: Boolean, default: false },
  currentStatus: { type: String, default: 'Active' },
  starting: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
  searchEnabled: { type: Boolean, default: true },
  deleteEnabled: { type: Boolean, default: true },
})

const emit = defineEmits([
  'select',
  'new',
  'status-change',
  'toggle',
  'search',
  'delete',
])

const statusOptions = [
  { value: 'Active', label: 'Active' },
  { value: 'Archived', label: 'Archived' },
]

const dateOptions = [
  { value: 'all', label: 'All' },
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
]

const query = ref('')
const dateRange = ref('all')
const hasAttachments = ref(false)

let debounceId = null

function emitSearch() {
  emit('search', {
    query: query.value.trim(),
    dateRange: dateRange.value,
    hasAttachments: hasAttachments.value,
    status: props.currentStatus,
  })
}

function onSearchInput() {
  if (debounceId) clearTimeout(debounceId)
  debounceId = setTimeout(() => emitSearch(), 220)
}

function clearSearch() {
  query.value = ''
  emitSearch()
}

function setDateRange(value) {
  dateRange.value = value
  emitSearch()
}

function onStatusChange(value) {
  emit('status-change', value)
  // Keep the search context aligned to the new status.
  if (query.value || dateRange.value !== 'all' || hasAttachments.value) {
    setTimeout(() => emitSearch(), 0)
  }
}

function onDelete(row) {
  emit('delete', row)
}

// When the parent switches status externally, do not strand the filters.
watch(
  () => props.currentStatus,
  () => {
    if (query.value || dateRange.value !== 'all' || hasAttachments.value) {
      emitSearch()
    }
  },
)

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
