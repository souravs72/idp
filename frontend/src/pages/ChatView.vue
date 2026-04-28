<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="flex h-screen w-full overflow-hidden bg-gray-100 dark:bg-gray-950">
    <ConversationList
      :sessions="store.sessions"
      :active-id="store.currentId"
      :loading="store.sessionsLoading"
      :current-status="status"
      @select="onSelect"
      @new="dialogOpen = true"
      @status-change="onStatusChange"
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
          <router-link
            to="/"
            class="text-[11px] text-blue-700 hover:underline dark:text-blue-300"
          >
            ← Back to upload
          </router-link>
        </div>
      </header>

      <div
        v-if="!store.currentId"
        class="flex flex-1 items-center justify-center text-sm text-gray-500"
      >
        <div class="text-center">
          <div class="text-lg font-medium text-gray-700 dark:text-gray-200">
            Welcome to the IDP Assistant
          </div>
          <div class="mt-1 text-xs text-gray-500">
            Pick a conversation on the left, or
            <button
              class="font-medium text-blue-700 hover:underline dark:text-blue-300"
              @click="dialogOpen = true"
            >
              start a new one
            </button>
            .
          </div>
        </div>
      </div>

      <div
        v-else
        ref="scrollEl"
        class="flex-1 space-y-4 overflow-y-auto bg-gray-100 p-4 dark:bg-gray-950"
      >
        <MessageBubble
          v-for="msg in store.visibleMessages"
          :key="msg.name"
          :message="msg"
          @confirmed="onConfirmed"
        />
        <ThinkingIndicator />
        <div
          v-if="store.agentState.lastError"
          class="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {{ store.agentState.lastError }}
        </div>
      </div>

      <ChatInput
        v-if="store.currentId"
        :disabled="store.agentState.running"
        @send="onSend"
      />

      <footer
        v-if="footerStats"
        class="border-t border-gray-200 bg-white px-4 py-1 text-[11px] text-gray-500 dark:border-gray-700 dark:bg-gray-900"
      >
        {{ footerStats }}
      </footer>
    </main>

    <NewConversationDialog
      :open="dialogOpen"
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
import NewConversationDialog from '@/components/chat/NewConversationDialog.vue'

import { useConversationStore } from '@/stores/conversation'
import { useConversation } from '@/composables/useConversation'
import { useAgent } from '@/composables/useAgent'
import { useConversationRealtime } from '@/composables/useRealtimeEvents'

const store = useConversationStore()
const route = useRoute()
const router = useRouter()
const { refreshSessions, loadConversation, archiveConversation } =
  useConversation()
const { send } = useAgent()

const status = ref('Active')
const dialogOpen = ref(false)
const scrollEl = ref(null)

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
    nextTick(scrollToBottom)
  },
  idp_conversation_error(payload) {
    store.setAgentError(
      payload.error || `Error (${payload.error_code || 'unknown'})`,
    )
  },
  idp_conversation_complete() {
    store.setAgentSummary(null)
  },
})

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

function scrollToBottom() {
  const el = scrollEl.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

async function onSelect(id) {
  if (id === store.currentId) return
  router.push({ name: 'ChatConversation', params: { id } })
}

async function onStatusChange(value) {
  status.value = value
  await refreshSessions({ status: value })
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
  try {
    await send({ content, attachments })
    await refreshSessions({ status: status.value })
  } catch (err) {
    // surfaced via store.agentState.lastError
  }
}

function onConfirmed() {
  // ConfirmationCardUI calls confirm() which already triggers run_agent;
  // this hook lets us refresh sidebar metadata after submit.
  refreshSessions({ status: status.value })
}

async function onCreated(out) {
  if (out?.conversation_id) {
    await refreshSessions({ status: status.value })
    router.push({
      name: 'ChatConversation',
      params: { id: out.conversation_id },
    })
  }
}

onMounted(async () => {
  await refreshSessions({ status: status.value })
})
</script>
