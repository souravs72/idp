<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="flex w-full" :class="alignClass">
    <div class="max-w-[85%] space-y-2">
      <div class="flex items-center gap-2 text-xs text-gray-500">
        <span class="font-medium">{{ roleLabel }}</span>
        <span v-if="message.created_on">{{ formattedTime }}</span>
        <span v-if="usageLabel" class="text-[11px] text-gray-400">
          · {{ usageLabel }}
        </span>
      </div>

      <!-- Tool-call (assistant requesting a tool) -->
      <div
        v-if="isAssistantToolRequest"
        class="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs dark:border-blue-900 dark:bg-blue-950"
      >
        <div class="font-medium text-blue-800 dark:text-blue-200">
          Calling tool:
          <code class="font-mono">{{ message.tool_name }}</code>
        </div>
        <details v-if="parsedToolArgs" class="mt-1">
          <summary class="cursor-pointer text-blue-700 dark:text-blue-300">
            View arguments
          </summary>
          <pre
            class="mt-2 overflow-x-auto rounded bg-blue-100 p-2 text-[11px] dark:bg-blue-900"
          >{{ formatJson(parsedToolArgs) }}</pre>
        </details>
      </div>

      <!-- Tool result -->
      <div
        v-if="isToolResult"
        class="rounded-md border bg-gray-50 px-3 py-2 text-xs dark:bg-gray-900"
        :class="
          toolSucceeded
            ? 'border-green-200 dark:border-green-900'
            : 'border-red-300 dark:border-red-900'
        "
      >
        <div class="flex items-center gap-2">
          <span
            class="inline-flex h-2 w-2 rounded-full"
            :class="toolSucceeded ? 'bg-green-500' : 'bg-red-500'"
          />
          <span class="font-medium">
            <code class="font-mono">{{ message.tool_name }}</code>
            {{ toolSucceeded ? 'completed' : 'failed' }}
          </span>
          <span
            v-if="parsedToolResult?.error_code"
            class="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-mono text-red-700 dark:bg-red-900 dark:text-red-200"
          >
            {{ parsedToolResult.error_code }}
          </span>
        </div>
        <div
          v-if="parsedToolResult?.error"
          class="mt-2 whitespace-pre-wrap text-red-700 dark:text-red-300"
        >
          {{ parsedToolResult.error }}
        </div>
        <details v-if="parsedToolResult?.data" class="mt-2">
          <summary class="cursor-pointer text-gray-600 dark:text-gray-300">
            View result data
          </summary>
          <pre
            class="mt-2 max-h-64 overflow-auto rounded bg-gray-100 p-2 text-[11px] dark:bg-gray-800"
          >{{ formatJson(parsedToolResult.data) }}</pre>
        </details>
      </div>

      <!-- Plain text content -->
      <div
        v-if="hasText && !isErrorCard"
        class="rounded-lg px-4 py-3 text-sm leading-relaxed shadow-sm"
        :class="bubbleClass"
      >
        <div
          v-if="renderAsMarkdown"
          class="idp-markdown space-y-2"
          v-html="renderedMarkdown"
        />
        <pre
          v-else
          class="whitespace-pre-wrap font-sans"
        >{{ message.content }}</pre>
      </div>

      <!-- Friendly error card -->
      <div
        v-if="isErrorCard"
        class="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm dark:border-red-900 dark:bg-red-950"
      >
        <div class="flex items-start gap-2">
          <span aria-hidden="true" class="text-base leading-none">⚠️</span>
          <div class="flex-1">
            <div class="font-medium text-red-800 dark:text-red-200">
              {{ errorPayload?.friendly_message || message.content }}
            </div>
            <div
              v-if="errorPayload?.error_code"
              class="mt-1 text-[11px] font-mono text-red-700 dark:text-red-300"
            >
              {{ errorPayload.error_code }}
            </div>
            <details
              v-if="errorPayload?.details_for_admin"
              class="mt-2 text-[11px] text-red-700 dark:text-red-300"
            >
              <summary class="cursor-pointer">Admin details</summary>
              <pre
                class="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-red-100 p-2 dark:bg-red-900"
              >{{ formatJson(errorPayload.details_for_admin) }}</pre>
            </details>
          </div>
        </div>
      </div>

      <!-- Card payload (Phase 20) -->
      <ConfirmationCardUI
        v-if="hasCard && !isErrorCard"
        :message="message"
        @confirmed="$emit('confirmed', $event)"
        @focus-source="$emit('focus-source', $event)"
      />

      <!-- Phase 36 D1 — ComparisonCard renderer -->
      <ComparisonCardUI
        v-if="isComparisonCard"
        :message="message"
      />

      <!-- UpdateCard renderer (update_document dry-run output) -->
      <UpdateCardUI
        v-if="isUpdateCard"
        :message="message"
      />

      <!-- Attachments -->
      <div v-if="parsedAttachments.length" class="space-y-1">
        <a
          v-for="att in parsedAttachments"
          :key="att.file_url || att.file_id"
          :href="att.file_url"
          target="_blank"
          class="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-1.5 text-xs hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700"
        >
          <span aria-hidden="true">📎</span>
          <span class="font-medium">{{ att.file_name || att.file_url }}</span>
        </a>
      </div>

      <!-- Error (legacy / non-card error rows).
           Suppress when the tool-result block above already surfaces
           the same string, or when an ErrorCard is rendering it — we
           used to show the same message three times on a failed tool
           call. -->
      <div
        v-if="showLegacyErrorBlock"
        class="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
      >
        {{ message.error }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import ConfirmationCardUI from './ConfirmationCardUI.vue'
import ComparisonCardUI from './ComparisonCardUI.vue'
import UpdateCardUI from './UpdateCardUI.vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({
  message: { type: Object, required: true },
})

defineEmits(['confirmed', 'focus-source'])

const ROLE_LABEL = {
  user: 'You',
  assistant: 'Assistant',
  tool: 'Tool',
  system: 'System',
}

const roleLabel = computed(
  () => ROLE_LABEL[props.message.role] || props.message.role || 'Message',
)

const alignClass = computed(() =>
  props.message.role === 'user' ? 'justify-end' : 'justify-start',
)

const bubbleClass = computed(() => {
  if (props.message.role === 'user') {
    return 'bg-blue-600 text-white'
  }
  return 'bg-white border border-gray-200 dark:bg-gray-800 dark:border-gray-700 text-gray-900 dark:text-gray-100'
})

const formattedTime = computed(() => {
  const v = props.message.created_on
  if (!v) return ''
  try {
    return new Date(v).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch (_) {
    return v
  }
})

const usageLabel = computed(() => {
  const t_in = props.message.tokens_in || 0
  const t_out = props.message.tokens_out || 0
  if (!t_in && !t_out) return ''
  return `${t_in}↑ ${t_out}↓ tokens`
})

const parsedToolArgs = computed(() => safeJson(props.message.tool_arguments))
const parsedToolResult = computed(() => safeJson(props.message.tool_result))
const parsedAttachments = computed(() => {
  const v = safeJson(props.message.attachments)
  return Array.isArray(v) ? v : []
})

const isAssistantToolRequest = computed(
  () => props.message.role === 'assistant' && !!props.message.tool_name,
)

const isToolResult = computed(() => props.message.role === 'tool')
const toolSucceeded = computed(() => {
  const r = parsedToolResult.value
  if (!r) return true
  return r.success !== false
})

const hasText = computed(() => {
  // Suppress empty assistant strings when there's only a tool call.
  const c = (props.message.content || '').trim()
  if (!c) return false
  if (props.message.role === 'tool') return false
  return true
})

const renderAsMarkdown = computed(() => props.message.role === 'assistant')
const renderedMarkdown = computed(() =>
  renderAsMarkdown.value ? renderMarkdown(props.message.content || '') : '',
)

const hasCard = computed(() => {
  // Only the ConfirmationCard renderer lives in ConfirmationCardUI.
  // InfoCard / ErrorCard / other card types are surfaced by the plain
  // text bubble (and the dedicated error block below).  Rendering an
  // InfoCard through ConfirmationCardUI produced an empty yellow
  // "Confirmation required" stub after Save Draft (Phase 24 fix).
  return (
    props.message.rendered_card_type === 'ConfirmationCard' &&
    !!props.message.rendered_card_payload
  )
})

const isErrorCard = computed(
  () => props.message.rendered_card_type === 'ErrorCard',
)

const isComparisonCard = computed(
  () =>
    props.message.rendered_card_type === 'ComparisonCard' &&
    !!props.message.rendered_card_payload,
)

const isUpdateCard = computed(
  () =>
    props.message.rendered_card_type === 'UpdateCard' &&
    !!props.message.rendered_card_payload,
)

const showLegacyErrorBlock = computed(() => {
  if (!props.message.error || isErrorCard.value) return false
  // Skip when the tool-result card already surfaces the same string.
  const r = parsedToolResult.value
  if (
    isToolResult.value &&
    r &&
    typeof r.error === 'string' &&
    r.error.trim() === String(props.message.error).trim()
  ) {
    return false
  }
  return true
})

const errorPayload = computed(() => {
  if (!isErrorCard.value) return null
  return safeJson(props.message.rendered_card_payload) || null
})

function safeJson(value) {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch (_) {
    return null
  }
}

function formatJson(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch (_) {
    return String(obj)
  }
}
</script>

<style scoped>
.idp-markdown :deep(p) {
  margin: 0.25rem 0;
}
.idp-markdown :deep(h1),
.idp-markdown :deep(h2),
.idp-markdown :deep(h3) {
  font-weight: 600;
  margin: 0.5rem 0 0.25rem;
}
.idp-markdown :deep(h1) { font-size: 1rem; }
.idp-markdown :deep(h2) { font-size: 0.9rem; }
.idp-markdown :deep(h3) { font-size: 0.85rem; }
.idp-markdown :deep(ul),
.idp-markdown :deep(ol) {
  margin: 0.25rem 0;
  padding-left: 1.25rem;
}
.idp-markdown :deep(ul) { list-style-type: disc; }
.idp-markdown :deep(ol) { list-style-type: decimal; }
.idp-markdown :deep(strong) {
  font-weight: 600;
}
.idp-markdown :deep(em) {
  font-style: italic;
}
.idp-markdown :deep(pre) {
  margin: 0.5rem 0;
  overflow-x: auto;
  border-radius: 0.25rem;
  background: #1f2937;
  padding: 0.5rem;
  font-size: 0.75rem;
  color: #f3f4f6;
}
.idp-markdown :deep(code) {
  background: #f3f4f6;
  border-radius: 0.2rem;
  padding: 0.1rem 0.3rem;
  font-size: 0.85em;
  font-family: ui-monospace, monospace;
}
.idp-markdown :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
}
.idp-markdown :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.75rem;
  margin: 0.5rem 0;
}
.idp-markdown :deep(th),
.idp-markdown :deep(td) {
  border: 1px solid #d1d5db;
  padding: 0.25rem 0.5rem;
  text-align: left;
}
.idp-markdown :deep(th) {
  background: #f9fafb;
  font-weight: 600;
}
.idp-markdown :deep(tr:nth-child(even) td) {
  background: #f9fafb;
}
.idp-markdown :deep(blockquote) {
  border-left: 3px solid #d1d5db;
  margin: 0.25rem 0;
  padding-left: 0.75rem;
  color: #6b7280;
}
.idp-markdown :deep(a) {
  color: #2563eb;
  text-decoration: underline;
}
</style>
