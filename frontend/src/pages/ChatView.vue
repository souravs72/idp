<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="flex h-screen w-full overflow-hidden bg-gray-100 dark:bg-gray-950">
    <ConversationList
      :sessions="store.sessions"
      :active-id="store.currentId"
      :loading="store.sessionsLoading"
      :current-status="status"
      :starting="startingConversation"
      :collapsed="sidebarCollapsed"
      :search-enabled="sidebarSearchEnabled"
      :delete-enabled="conversationDeleteEnabled"
      @select="onSelect"
      @new="startNewConversation"
      @status-change="onStatusChange"
      @toggle="sidebarCollapsed = !sidebarCollapsed"
      @search="onSidebarSearch"
      @delete="onDeleteConversation"
    />

    <main class="flex flex-1 flex-col overflow-hidden">
      <header
        class="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-900"
      >
        <div class="min-w-0">
          <div class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
            {{ headerTitle }}
          </div>
          <div
            v-if="headerSubtitle"
            class="truncate text-[11px] text-gray-500 dark:text-gray-400"
          >
            {{ headerSubtitle }}
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="store.currentDetail"
            type="button"
            class="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
            @click="onArchive"
          >
            Archive
          </button>
        </div>
      </header>

      <div
        v-if="!store.currentId"
        class="flex flex-1 items-center justify-center bg-gray-50 p-6 text-sm text-gray-500 dark:bg-gray-950"
      >
        <div class="max-w-md text-center">
          <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-2xl dark:bg-blue-950">
            💬
          </div>
          <div class="text-lg font-semibold text-gray-800 dark:text-gray-100">
            Welcome to the IDP Assistant
          </div>
          <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Upload a document or ask a question — I can extract data, draft
            ERPNext records, and walk you through confirmations.
          </div>
          <button
            class="mt-4 rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            :disabled="startingConversation"
            @click="startNewConversation"
          >
            {{ startingConversation ? 'Starting…' : 'Start a new conversation' }}
          </button>
          <div class="mt-3 text-[11px] text-gray-400">
            Or pick an existing one from the sidebar.
          </div>
        </div>
      </div>

      <div
        v-else
        ref="scrollEl"
        class="relative flex-1 space-y-4 overflow-y-auto bg-gray-100 p-4 dark:bg-gray-950"
        @scroll="onScroll"
      >
        <div
          v-if="!store.visibleMessages.length && !store.agentState.running"
          class="mx-auto max-w-md rounded-lg border border-dashed border-gray-300 bg-white p-4 text-center text-xs text-gray-500 dark:border-gray-700 dark:bg-gray-900"
        >
          <div class="mb-1 text-sm font-medium text-gray-700 dark:text-gray-200">
            New conversation ready
          </div>
          <div>
            Drop a document into the box below or type a question — for
            example,
            <em>“extract data and create a Purchase Invoice from this PDF.”</em>
          </div>

          <!-- Phase 31 G14 — suggested prompt chips. -->
          <div
            v-if="suggestedPromptChips.length"
            class="mt-3 flex flex-wrap justify-center gap-1.5"
          >
            <button
              v-for="(p, i) in suggestedPromptChips"
              :key="i"
              type="button"
              class="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] text-blue-800 hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200 dark:hover:bg-blue-900"
              @click="onPickSuggested(p)"
            >
              {{ p }}
            </button>
          </div>
        </div>

        <MessageBubble
          v-for="msg in store.visibleMessages"
          :key="msg.name"
          :message="msg"
          @confirmed="onConfirmed"
          @focus-source="onFocusSource"
        />
        <!-- Phase 30 — progress banner docks ABOVE the streaming
             bubble per roadmap §30.7. -->
        <ProgressBanner />
        <!-- Phase 30 — ephemeral streaming bubble.  Removed by the
             realtime handlers once the assistant ``IDP Message`` row
             lands (or the turn errors / completes / is cancelled). -->
        <div
          v-if="store.streamingState.active"
          class="flex justify-start"
        >
          <div
            class="max-w-[80%] rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          >
            <span class="whitespace-pre-wrap">{{ store.streamingState.text }}</span>
            <span class="ml-0.5 inline-block animate-pulse text-gray-400">▍</span>
            <div
              v-if="store.streamingState.cancelling"
              class="mt-1 text-[10px] italic text-gray-500"
            >
              Cancelling…
            </div>
          </div>
        </div>
        <ThinkingIndicator />
        <div
          v-if="store.agentState.lastError"
          class="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {{ store.agentState.lastError }}
        </div>

        <button
          v-if="showScrollButton"
          type="button"
          class="sticky bottom-4 ml-auto block rounded-full bg-gray-900 px-3 py-1 text-[11px] font-medium text-white shadow-md hover:bg-gray-800"
          @click="scrollToBottom(true)"
        >
          ↓ Jump to latest
        </button>
      </div>

      <ChatInput
        v-if="store.currentId"
        :disabled="store.agentState.running"
        :cancellable="store.agentState.running"
        :cancelling="cancelling"
        @send="onSend"
        @cancel="onCancel"
      />

      <!-- Phase 31 G12 — token / cost chip footer.  Falls back to the
           legacy plain footer when ``enable_cost_footer`` is disabled. -->
      <CostFooter v-if="costFooterEnabled" />
      <footer
        v-else-if="footerStats"
        class="border-t border-gray-200 bg-white px-4 py-1 text-[11px] text-gray-500 dark:border-gray-700 dark:bg-gray-900"
      >
        {{ footerStats }}
      </footer>
    </main>

    <!-- Phase 29 — click-to-source PDF preview panel.  Renders only
         when a field with a recorded bbox is clicked. -->
    <aside
      v-if="focusSource"
      class="flex w-[420px] max-w-[40vw] flex-col border-l border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900"
    >
      <div class="flex items-center justify-between border-b border-gray-200 px-3 py-2 dark:border-gray-700">
        <div class="min-w-0">
          <div class="truncate text-xs font-semibold text-gray-700 dark:text-gray-200">
            Source: {{ focusSource.field || 'document' }}
          </div>
          <div class="truncate text-[10px] text-gray-500 dark:text-gray-400">
            {{ focusSourceFileName }}
            <span v-if="focusSource.page">· page {{ focusSource.page }}</span>
          </div>
        </div>
        <button
          type="button"
          class="rounded p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
          aria-label="Close source preview"
          @click="focusSource = null"
        >
          ✕
        </button>
      </div>
      <div class="flex-1 overflow-auto p-3">
        <PdfPreview
          v-if="focusSourceFileUrl"
          :file-url="focusSourceFileUrl"
          :highlight="pdfHighlight"
        />
        <div
          v-else
          class="rounded border border-dashed border-gray-300 p-4 text-xs text-gray-500 dark:border-gray-700"
        >
          Could not resolve the source attachment for this field.
        </div>
      </div>
    </aside>

    <NewConversationDialog
      :open="dialogOpen"
      :prefill="dialogPrefill"
      @close="dialogOpen = false"
      @created="onCreated"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConversationList from '@/components/chat/ConversationList.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import ThinkingIndicator from '@/components/chat/ThinkingIndicator.vue'
import ProgressBanner from '@/components/chat/ProgressBanner.vue'
import NewConversationDialog from '@/components/chat/NewConversationDialog.vue'
import PdfPreview from '@/components/chat/PdfPreview.vue'
import CostFooter from '@/components/chat/CostFooter.vue'

import { useConversationStore } from '@/stores/conversation'
import { useConversation } from '@/composables/useConversation'
import { useAgent } from '@/composables/useAgent'
import { useConversationRealtime } from '@/composables/useRealtimeEvents'
import { useSettings } from '@/composables/useSettings'
import { useCost } from '@/composables/useCost'
import { useSuggestedPrompts } from '@/composables/useSuggestedPrompts'
import { cancelTurn } from '@/utils/api'

const store = useConversationStore()
const route = useRoute()
const router = useRouter()
const {
  refreshSessions,
  loadConversation,
  archiveConversation,
  deleteConversation,
  searchSessions,
  quickStart,
} = useConversation()
const { send } = useAgent()
const { settings, load: loadSettings } = useSettings()
const { confirmIfNeeded } = useCost()
const {
  prompts: suggestedPrompts,
  load: loadSuggestedPrompts,
} = useSuggestedPrompts()

// Phase 31 — sidebar collapse / settings-gated UI flags.
const sidebarCollapsed = ref(false)

function flag(key, fallback = true) {
  const v = settings.value?.[key]
  if (v == null) return fallback
  return !!Number(v)
}

const sidebarSearchEnabled = computed(() => flag('enable_sidebar_search'))
const conversationDeleteEnabled = computed(
  () => flag('enable_conversation_delete'),
)
const costFooterEnabled = computed(() => flag('enable_cost_footer'))

const suggestedPromptChips = computed(() => {
  if (!flag('enable_suggested_prompts')) return []
  const list = suggestedPrompts.value
  return Array.isArray(list) ? list.slice(0, 6) : []
})

// Track the last-applied sidebar search payload so refreshSessions and
// status-change handlers can re-run it (otherwise the unfiltered list
// would silently replace the filtered results).
const activeSearch = ref(null)

const dialogPrefill = ref(null)
const startingConversation = ref(false)

// Phase 29 — click-to-source side panel.
// Holds `{ file_id, file_url?, field, page, bbox }` of the most-recently
// clicked confidence dot.  Cleared when the user closes the panel or
// switches conversation so we don't leak the previous PDF render.
const focusSource = ref(null)

const status = ref('Active')
const dialogOpen = ref(false)
const scrollEl = ref(null)
const showScrollButton = ref(false)
const SCROLL_PINNED_THRESHOLD = 80

const headerTitle = computed(() => {
  const d = store.currentDetail
  if (!d) return 'IDP Assistant'
  return d.title || `Conversation ${d.conversation_id}`
})

const headerSubtitle = computed(() => {
  const d = store.currentDetail
  if (!d) return ''
  const parts = []
  if (d.target_doctype) parts.push(d.target_doctype)
  if (d.company) parts.push(d.company)
  if (d.llm_model) parts.push(d.llm_model)
  if (d.output_language) parts.push(`output: ${d.output_language}`)
  return parts.join(' · ')
})

const footerStats = computed(() => {
  const d = store.currentDetail
  if (!d) return ''
  const parts = []
  if (d.message_count) parts.push(`${d.message_count} msg`)
  if (d.total_tokens_used) parts.push(`${d.total_tokens_used} tokens`)
  if (d.estimated_cost_usd) {
    parts.push(`$${Number(d.estimated_cost_usd).toFixed(4)}`)
  }
  return parts.join(' · ')
})

// -- realtime wiring -------------------------------------------------------
const conversationIdRef = computed(() => store.currentId)
useConversationRealtime(conversationIdRef, {
  idp_conversation_thinking(payload) {
    store.setAgentThinking(payload.iteration || 0)
  },
  idp_conversation_tool_start(payload) {
    store.setAgentTool(payload.name || null)
  },
  idp_conversation_tool_end() {
    store.setAgentTool(null)
  },
  idp_conversation_message(payload) {
    if (payload.message) store.appendMessage(payload.message)
    // The persisted row supersedes the streaming buffer for this seq.
    store.resetStreaming()
    store.resetProgress()
    nextTick(scrollToBottom)
  },
  idp_conversation_error(payload) {
    store.setAgentError(
      payload.error || `Error (${payload.error_code || 'unknown'})`,
    )
    store.resetStreaming()
    store.resetProgress()
  },
  idp_conversation_complete() {
    store.setAgentSummary(null)
    store.resetStreaming()
    store.resetProgress()
  },
  // Phase 30 — incremental assistant prose deltas.
  idp_conversation_token(payload) {
    store.appendStreamToken(payload)
    nextTick(scrollToBottom)
  },
  idp_conversation_tool_call_start(payload) {
    if (payload?.tool_name) store.setAgentTool(payload.tool_name)
  },
  idp_conversation_progress(payload) {
    store.setProgress(payload)
  },
})

// -- Phase 30: cancel handling --------------------------------------------
const cancelling = ref(false)
async function onCancel() {
  if (cancelling.value) return
  if (!store.currentId) return
  cancelling.value = true
  store.markStreamCancelling()
  try {
    await cancelTurn(store.currentId)
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[ChatView] cancel_turn failed', err)
  } finally {
    // Reset the local flag once the agent loop emits ``complete`` /
    // ``message`` — fall back to a short timeout in case the run had
    // already terminated server-side before our request landed.
    setTimeout(() => {
      cancelling.value = false
    }, 800)
  }
}

// -- routing sync ----------------------------------------------------------
watch(
  () => route.params.id,
  async (id) => {
    if (id && id !== store.currentId) {
      try {
        await loadConversation(id)
        nextTick(scrollToBottom)
      } catch (err) {
        // If load fails (e.g. archived/no permission) bounce to /chat.
        // eslint-disable-next-line no-console
        console.error('[ChatView] failed to load conversation', err)
        router.replace({ name: 'ChatHome' })
      }
    } else if (!id) {
      store.clearCurrent()
    }
  },
  { immediate: true },
)

watch(
  () => store.visibleMessages.length,
  () => {
    nextTick(scrollToBottom)
  },
)

function scrollToBottom(force = false) {
  const el = scrollEl.value
  if (!el) return
  if (!force) {
    // Only auto-scroll when the user is already near the bottom; this
    // prevents yanking them away while they're reading older messages.
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    if (distance > SCROLL_PINNED_THRESHOLD) {
      showScrollButton.value = true
      return
    }
  }
  el.scrollTop = el.scrollHeight
  showScrollButton.value = false
}

function onScroll() {
  const el = scrollEl.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  showScrollButton.value = distance > SCROLL_PINNED_THRESHOLD
}

async function onSelect(id) {
  if (id === store.currentId) return
  router.push({ name: 'ChatConversation', params: { id } })
}

async function onStatusChange(value) {
  status.value = value
  if (activeSearch.value) {
    await searchSessions({ ...activeSearch.value, status: value })
  } else {
    await refreshSessions({ status: value })
  }
}

// Phase 31 G15 — sidebar search/filter.  An empty payload (no query +
// default chips) reverts to the plain list to keep parity with the
// pre-Phase-31 behaviour.
async function onSidebarSearch(payload) {
  const isEmpty =
    !payload?.query && payload?.dateRange === 'all' && !payload?.hasAttachments
  if (isEmpty) {
    activeSearch.value = null
    await refreshSessions({ status: status.value })
    return
  }
  activeSearch.value = payload
  await searchSessions(payload)
}

async function onDeleteConversation(row) {
  if (!row?.name) return
  const title = row.title || `Conversation ${row.name}`
  if (!window.confirm(`Delete "${title}"? This cannot be undone.`)) return
  try {
    await deleteConversation(row.name)
    if (route.params.id === row.name) {
      router.replace({ name: 'ChatHome' })
    }
    if (activeSearch.value) {
      await searchSessions({ ...activeSearch.value, status: status.value })
    } else {
      await refreshSessions({ status: status.value })
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[ChatView] delete failed', err)
    window.alert(err?.message || 'Failed to delete conversation.')
  }
}

// Phase 31 G14 — clicking a suggested prompt chip drops the text into
// the composer.  ChatInput exposes a custom event API, so we instead
// dispatch a window-level event that the input listens for; this keeps
// the chip free of tight coupling to ChatInput's internals.
function onPickSuggested(text) {
  if (!text) return
  window.dispatchEvent(
    new CustomEvent('idp:chat-input:prefill', { detail: { text } }),
  )
}

async function onArchive() {
  if (!store.currentId) return
  if (!window.confirm('Archive this conversation?')) return
  try {
    await archiveConversation(store.currentId)
    router.push({ name: 'ChatHome' })
    await refreshSessions({ status: status.value })
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error('[ChatView] archive failed', err)
  }
}

async function onSend({ content, attachments }) {
  // Phase 31 G13 — pre-flight cost check.  Cancelling the modal aborts
  // the send and consumes no token budget.
  const proceed = await confirmIfNeeded({
    conversationId: store.currentId,
    content,
    attachments,
  })
  if (!proceed) return
  try {
    await send({ content, attachments })
    if (activeSearch.value) {
      await searchSessions({ ...activeSearch.value, status: status.value })
    } else {
      await refreshSessions({ status: status.value })
    }
  } catch (err) {
    // surfaced via store.agentState.lastError
  }
}

function onConfirmed() {
  // ConfirmationCardUI calls confirm() which already triggers run_agent;
  // this hook lets us refresh sidebar metadata after submit.
  refreshSessions({ status: status.value })
}

// Phase 29 — receive `focus-source` events from ConfirmationCardUI via
// MessageBubble.  Payload shape: { file_id, field, page, bbox }.
function onFocusSource(payload) {
  if (!payload) {
    focusSource.value = null
    return
  }
  focusSource.value = { ...payload }
}

const focusAttachment = computed(() => {
  const fs = focusSource.value
  if (!fs) return null
  const attachments = store.currentDetail?.attachments || []
  if (fs.file_url) {
    // Direct URL provided — find a name for the header label.
    return (
      attachments.find((a) => a.file_url === fs.file_url) || {
        file_url: fs.file_url,
        file_name: fs.file_url,
      }
    )
  }
  if (fs.file_id) {
    return attachments.find((a) => a.file_id === fs.file_id) || null
  }
  return null
})

const focusSourceFileUrl = computed(() => focusAttachment.value?.file_url || '')
const focusSourceFileName = computed(
  () => focusAttachment.value?.file_name || focusAttachment.value?.file_url || '',
)

// PdfPreview expects a single ``highlight`` prop shaped { page, bbox }
// — assemble it from the focusSource payload emitted by the card.
const pdfHighlight = computed(() => {
  const fs = focusSource.value
  if (!fs) return null
  const page = Number(fs.page) || 1
  const bbox = Array.isArray(fs.bbox) ? fs.bbox : null
  if (!bbox) return { page, bbox: null }
  return { page, bbox }
})

// Clear the source panel whenever the active conversation changes — the
// previously focused field belongs to a different document.
watch(
  () => store.currentId,
  () => {
    focusSource.value = null
  },
)

async function onCreated(out) {
  if (out?.conversation_id) {
    await refreshSessions({ status: status.value })
    router.push({
      name: 'ChatConversation',
      params: { id: out.conversation_id },
    })
  }
}

/**
 * Start a new conversation.  Prefer the IDP Settings defaults so the
 * user never sees the picker; only fall back to the modal when the
 * settings are incomplete.
 */
async function startNewConversation() {
  if (startingConversation.value) return
  startingConversation.value = true
  try {
    const out = await quickStart()
    if (out?.needsModal) {
      dialogPrefill.value = out.defaults || null
      dialogOpen.value = true
      return
    }
    if (out?.conversation_id) {
      await refreshSessions({ status: status.value })
      router.push({
        name: 'ChatConversation',
        params: { id: out.conversation_id },
      })
    }
  } catch (err) {
    // Fallback: open the picker so the user can supply values manually.
    // eslint-disable-next-line no-console
    console.warn('[ChatView] quickStart failed, opening picker', err)
    dialogPrefill.value = null
    dialogOpen.value = true
  } finally {
    startingConversation.value = false
  }
}

onMounted(async () => {
  // Load IDP Settings before fetching sessions so the feature-flag
  // computeds resolve before the sidebar renders.
  try {
    await loadSettings()
  } catch (_) {
    // Non-fatal — gated UI falls back to its built-in defaults.
  }
  await refreshSessions({ status: status.value })
  // Fire-and-forget; chips render once the cache populates.
  loadSuggestedPrompts()
})
</script>
