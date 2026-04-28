// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Subscribe to Frappe socket.io realtime events for a single IDP
 * Conversation.
 *
 * Frappe exposes ``window.frappe.realtime`` once the desk shell loads.
 * Inside the SPA we receive it via the boot context published by
 * ``idp/www/idp.py``.  When socket.io is unavailable (e.g. dev with no
 * websocket port), the composable degrades gracefully — callers can
 * still rely on the post-call response from ``run_agent`` to know the
 * loop has finished.
 *
 * Backend events emitted by ``IDPAgent._publish_event``:
 *   - idp_conversation_message       (new IDP Message persisted)
 *   - idp_conversation_thinking      (LLM round about to start)
 *   - idp_conversation_tool_start    (a tool dispatch began)
 *   - idp_conversation_tool_end      (a tool dispatch ended)
 *   - idp_conversation_error         (loop hit a stop-on-error)
 *   - idp_conversation_complete      (agent.run() finished)
 */

import { onBeforeUnmount, ref, watch } from 'vue'

const EVENT_NAMES = [
  'idp_conversation_message',
  'idp_conversation_thinking',
  'idp_conversation_tool_start',
  'idp_conversation_tool_end',
  'idp_conversation_error',
  'idp_conversation_complete',
]

function getRealtime() {
  if (typeof window === 'undefined') return null
  const f = window.frappe
  if (!f) return null
  return f.realtime || null
}

export function useConversationRealtime(conversationIdRef, handlers = {}) {
  const connected = ref(false)
  const subscriptions = []

  function unsubscribeAll() {
    const rt = getRealtime()
    while (subscriptions.length) {
      const { event, fn } = subscriptions.pop()
      try {
        if (rt && typeof rt.off === 'function') rt.off(event, fn)
      } catch (e) {
        // swallow
      }
    }
    connected.value = false
  }

  function subscribe(id) {
    unsubscribeAll()
    if (!id) return
    const rt = getRealtime()
    if (!rt || typeof rt.on !== 'function') return

    // Frappe's realtime client multiplexes via doc-level channels.
    try {
      if (typeof rt.doc_subscribe === 'function') {
        rt.doc_subscribe('IDP Conversation', id)
      }
    } catch (e) {
      // older frappe builds — ignore
    }

    EVENT_NAMES.forEach((event) => {
      const fn = (payload) => {
        // The agent always echoes the conversation id; filter to ours.
        if (payload && payload.conversation && payload.conversation !== id) {
          return
        }
        const handler = handlers[event]
        if (typeof handler === 'function') {
          try {
            handler(payload || {})
          } catch (err) {
            // eslint-disable-next-line no-console
            console.error(`[idp realtime] handler ${event} threw`, err)
          }
        }
      }
      rt.on(event, fn)
      subscriptions.push({ event, fn })
    })
    connected.value = true
  }

  watch(
    conversationIdRef,
    (id) => {
      subscribe(id)
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    unsubscribeAll()
  })

  return { connected }
}
