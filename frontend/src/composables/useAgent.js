// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Composable: drive the IDP agent loop from the chat UI.
 *
 *   const { send, confirm, busy } = useAgent()
 *   await send({ content: "...", attachments: [...] })
 *   await confirm({ messageId, action: "submit", edits: {...} })
 *
 * The composable:
 *   1. Writes the user's message optimistically into the store so the
 *      UI is responsive even before realtime events arrive.
 *   2. Calls ``run_agent``, which pushes realtime events while it runs.
 *   3. After completion, reloads the conversation to sync with the
 *      server's authoritative ordering / sequence numbers (in case
 *      sockets were unavailable).
 */

import { ref } from 'vue'
import { useConversationStore } from '@/stores/conversation'
import {
  confirmCard as apiConfirmCard,
  getConversation as apiGet,
  runAgent as apiRunAgent,
} from '@/utils/api'

export function useAgent() {
  const store = useConversationStore()
  const busy = ref(false)
  const lastError = ref(null)

  async function syncConversation(conversationId) {
    if (!conversationId) return
    try {
      const detail = await apiGet(conversationId)
      store.setCurrent(detail)
    } catch (err) {
      // Non-fatal: sockets might still have delivered the messages.
      // eslint-disable-next-line no-console
      console.warn('[useAgent] sync after run failed', err)
    }
  }

  async function send({
    content = '',
    attachments = [],
    userConfirmedAction = null,
  } = {}) {
    const conversationId = store.currentId
    if (!conversationId) {
      throw new Error('No active conversation')
    }
    busy.value = true
    store.setAgentRunning(true)
    store.setAgentError(null)
    try {
      const summary = await apiRunAgent({
        conversationId,
        content,
        attachments,
        userConfirmedAction,
      })
      store.setAgentSummary(summary)
      // Server returned an error envelope (LLM unavailable, OCR failed,
      // etc.).  Surface the friendly message — never the raw exception
      // class name or URL.
      if (summary && summary.error && summary.error.friendly_message) {
        const friendly = summary.error.friendly_message
        lastError.value = friendly
        store.setAgentError(friendly)
      }
      // Authoritative sync (covers cases where realtime is offline).
      await syncConversation(conversationId)
      return summary
    } catch (err) {
      // Network / transport failure.  Show a generic, friendly message
      // — never the raw URL or exception name.
      const friendly =
        'We couldn\'t reach the assistant right now. Please check your connection and try again.'
      lastError.value = friendly
      store.setAgentError(friendly)
      // Keep the original error for console diagnostics only.
      // eslint-disable-next-line no-console
      console.warn('[useAgent] run_agent transport error', err)
      throw err
    } finally {
      busy.value = false
      store.setAgentRunning(false)
    }
  }

  /**
   * Phase 24: confirm a ConfirmationCard.
   *
   * The backend ``confirm_card`` endpoint now performs the actual
   * ERPNext document creation directly (and attaches the uploaded
   * source files to the new record).
   *
   *   - ``submit``     → create + submit + attach
   *   - ``save_draft`` → create as Draft + attach
   *   - ``cancel``     → no-op (UI resets edits locally)
   *   - ``edit``       → handled in the card UI (no API call)
   *
   * After the call we re-sync the conversation so the new ack message
   * (and any persisted card mutation) shows up in the chat.
   */
  async function confirm({
    messageId,
    action,
    edits = null,
  }) {
    const conversationId = store.currentId
    if (!conversationId) throw new Error('No active conversation')
    if (!messageId) throw new Error('messageId is required')
    if (!action) throw new Error('action is required')

    busy.value = true
    try {
      const out = await apiConfirmCard({
        conversationId,
        messageId,
        action,
        editedPayload: edits || null,
      })

      // Surface backend-side errors (e.g. document insert failed)
      // through the same friendly-error channel as send().
      if (out && out.error && out.error.friendly_message) {
        lastError.value = out.error.friendly_message
        store.setAgentError(out.error.friendly_message)
      }

      // Reload so revalidation warnings, the mutated card payload, and
      // the ack assistant message surface in the chat surface.
      await syncConversation(conversationId)
      return out
    } catch (err) {
      const friendly =
        'We couldn\'t process your confirmation. Please reload the conversation and try again.'
      lastError.value = friendly
      store.setAgentError(friendly)
      // eslint-disable-next-line no-console
      console.warn('[useAgent] confirm_card error', err)
      throw err
    } finally {
      busy.value = false
    }
  }

  return { busy, lastError, send, confirm }
}
