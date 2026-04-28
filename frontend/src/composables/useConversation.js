// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Composable: conversation CRUD + sidebar management.
 *
 * Wraps the API client and writes results into the Pinia store so all
 * consumers stay in sync with one source of truth.
 */

import { ref } from 'vue'
import { useConversationStore } from '@/stores/conversation'
import {
  archiveConversation as apiArchive,
  createConversation as apiCreate,
  getConversation as apiGet,
  listConversations as apiList,
} from '@/utils/api'

export function useConversation() {
  const store = useConversationStore()
  const lastError = ref(null)

  async function refreshSessions(opts = {}) {
    store.sessionsLoading = true
    try {
      const rows = await apiList(opts)
      store.setSessions(rows || [])
      return rows || []
    } catch (err) {
      lastError.value = err?.message || String(err)
      throw err
    } finally {
      store.sessionsLoading = false
    }
  }

  async function loadConversation(conversationId) {
    if (!conversationId) {
      store.clearCurrent()
      return null
    }
    store.currentLoading = true
    try {
      const detail = await apiGet(conversationId)
      store.setCurrent(detail)
      return detail
    } catch (err) {
      lastError.value = err?.message || String(err)
      throw err
    } finally {
      store.currentLoading = false
    }
  }

  async function createConversation(payload = {}) {
    const out = await apiCreate(payload)
    if (out?.conversation_id) {
      // Optimistically push into the sidebar so it appears immediately.
      store.upsertSession({
        name: out.conversation_id,
        title: out.title || '',
        status: out.status || 'Active',
        modified: new Date().toISOString(),
        message_count: 0,
      })
    }
    return out
  }

  async function archiveConversation(conversationId) {
    const out = await apiArchive(conversationId)
    // Remove from active list / mark archived.
    const idx = store.sessions.findIndex((s) => s.name === conversationId)
    if (idx >= 0) {
      store.sessions[idx] = { ...store.sessions[idx], status: 'Archived' }
    }
    if (store.currentId === conversationId) {
      store.clearCurrent()
    }
    return out
  }

  return {
    lastError,
    refreshSessions,
    loadConversation,
    createConversation,
    archiveConversation,
  }
}
