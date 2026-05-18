// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Pinia store for the chatbot SPA (Phase 23).
 *
 * Holds:
 *  - sessions:        list of the user's conversations (sidebar)
 *  - currentId:       active conversation id (mirrors :id route param)
 *  - currentDetail:   { conversation_id, title, llm_*, attachments, ... }
 *  - messages:        ordered IDP Message rows for the active conversation
 *  - agentState:      { thinking, currentTool, lastError, lastSummary }
 *
 * The store never calls the API directly — that lives in
 * `composables/useConversation.js` and `useAgent.js`.  The store is the
 * single source of truth for components.
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useConversationStore = defineStore('idpConversation', () => {
  // -- sidebar / sessions ---------------------------------------------------
  const sessions = ref([])
  const sessionsLoading = ref(false)

  // -- active conversation --------------------------------------------------
  const currentId = ref(null)
  const currentDetail = ref(null)
  const currentLoading = ref(false)
  const messages = ref([])

  // -- agent run state ------------------------------------------------------
  const agentState = ref({
    running: false,
    thinking: false,
    iteration: 0,
    currentTool: null,
    lastError: null,
    lastSummary: null,
  })

  // -- Phase 30: streaming buffer + progress --------------------------------
  // While a turn is streaming we accumulate prose tokens here and the
  // chat surface renders an ephemeral assistant bubble keyed by
  // ``streamingSeq``.  When ``idp_conversation_message`` lands for the
  // same sequence we wipe the buffer so the persisted row takes over.
  const streamingState = ref({
    active: false,
    sequence: null,
    iteration: 0,
    text: '',
    cancelling: false,
  })
  const progressState = ref({
    message: '',
    tool: null,
    stage: null,
    receivedAt: 0,
  })

  // -- getters --------------------------------------------------------------
  const sortedMessages = computed(() => {
    return [...messages.value].sort((a, b) => {
      const sa = a.sequence ?? 0
      const sb = b.sequence ?? 0
      if (sa !== sb) return sa - sb
      return (a.created_on || '').localeCompare(b.created_on || '')
    })
  })

  const visibleMessages = computed(() => {
    // Hide raw system / "user_confirmation" acks from the chat surface.
    // The user_confirmation row may carry role="tool" (legacy) or
    // role="user" (Phase 24 — to satisfy Anthropic's tool_use_id rules).
    return sortedMessages.value.filter((m) => {
      if (m.role === 'system') return false
      if (m.tool_name === 'user_confirmation') return false
      return true
    })
  })

  // -- mutations ------------------------------------------------------------
  function setSessions(rows) {
    sessions.value = Array.isArray(rows) ? rows : []
  }

  function upsertSession(row) {
    if (!row?.name) return
    const idx = sessions.value.findIndex((s) => s.name === row.name)
    if (idx >= 0) {
      sessions.value[idx] = { ...sessions.value[idx], ...row }
    } else {
      sessions.value.unshift(row)
    }
  }

  function setCurrent(detail) {
    currentDetail.value = detail
    currentId.value = detail?.conversation_id || null
    messages.value = Array.isArray(detail?.messages) ? [...detail.messages] : []
  }

  function clearCurrent() {
    currentId.value = null
    currentDetail.value = null
    messages.value = []
    resetAgentState()
  }

  function appendMessage(row) {
    if (!row?.name) return
    const idx = messages.value.findIndex((m) => m.name === row.name)
    if (idx >= 0) {
      messages.value[idx] = { ...messages.value[idx], ...row }
    } else {
      messages.value.push(row)
    }
  }

  function patchMessage(name, patch) {
    const idx = messages.value.findIndex((m) => m.name === name)
    if (idx >= 0) {
      messages.value[idx] = { ...messages.value[idx], ...patch }
    }
  }

  function setAgentRunning(running) {
    agentState.value.running = running
    if (!running) {
      agentState.value.thinking = false
      agentState.value.currentTool = null
    }
  }

  function setAgentThinking(iteration) {
    agentState.value.thinking = true
    agentState.value.iteration = iteration || agentState.value.iteration
  }

  function setAgentTool(tool) {
    agentState.value.currentTool = tool
  }

  function setAgentError(err) {
    agentState.value.lastError = err
  }

  function setAgentSummary(summary) {
    agentState.value.lastSummary = summary
    agentState.value.thinking = false
    agentState.value.currentTool = null
  }

  function resetAgentState() {
    agentState.value = {
      running: false,
      thinking: false,
      iteration: 0,
      currentTool: null,
      lastError: null,
      lastSummary: null,
    }
    resetStreaming()
    resetProgress()
  }

  // -- Phase 30 mutations ---------------------------------------------------
  function appendStreamToken(payload) {
    const seq = payload?.message_seq ?? payload?.sequence ?? null
    const iteration = payload?.iteration ?? streamingState.value.iteration ?? 0
    const text = String(payload?.text ?? '')
    if (!text) return
    if (!streamingState.value.active || streamingState.value.sequence !== seq) {
      streamingState.value = {
        active: true,
        sequence: seq,
        iteration,
        text,
        cancelling: false,
      }
    } else {
      streamingState.value.text += text
      streamingState.value.iteration = iteration
    }
  }

  function markStreamCancelling() {
    if (streamingState.value.active) {
      streamingState.value.cancelling = true
    }
  }

  function resetStreaming() {
    streamingState.value = {
      active: false,
      sequence: null,
      iteration: 0,
      text: '',
      cancelling: false,
    }
  }

  function setProgress(payload) {
    progressState.value = {
      message: String(payload?.user_visible_message ?? ''),
      tool: payload?.tool ?? null,
      stage: payload?.stage ?? null,
      receivedAt: Date.now(),
    }
  }

  function resetProgress() {
    progressState.value = {
      message: '',
      tool: null,
      stage: null,
      receivedAt: 0,
    }
  }

  return {
    // state
    sessions,
    sessionsLoading,
    currentId,
    currentDetail,
    currentLoading,
    messages,
    agentState,
    streamingState,
    progressState,
    // getters
    sortedMessages,
    visibleMessages,
    // mutations
    setSessions,
    upsertSession,
    setCurrent,
    clearCurrent,
    appendMessage,
    patchMessage,
    setAgentRunning,
    setAgentThinking,
    setAgentTool,
    setAgentError,
    setAgentSummary,
    resetAgentState,
    // Phase 30
    appendStreamToken,
    markStreamCancelling,
    resetStreaming,
    setProgress,
    resetProgress,
  }
})
