// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Subscribe to Frappe Socket.IO realtime events for a single IDP
 * Conversation.
 *
 * Wiring (Phase 30 — standalone SPA): the previous implementation
 * reached for ``window.frappe.realtime`` which only exists inside the
 * Desk shell.  Inside our standalone Vue app we instead use the
 * Manager-backed singleton created by ``src/socket.js`` — see
 * :func:`initSocket` (bootstrapped from ``main.js``).
 *
 * Backend events emitted by ``IDPAgent._publish_event``:
 *   - idp_conversation_message            (new IDP Message persisted)
 *   - idp_conversation_thinking           (LLM round about to start)
 *   - idp_conversation_tool_start         (a tool dispatch began)
 *   - idp_conversation_tool_end           (a tool dispatch ended)
 *   - idp_conversation_error              (loop hit a stop-on-error)
 *   - idp_conversation_complete           (agent.run() finished)
 *
 * Phase 30 — streaming & progress:
 *   - idp_conversation_token              (batched assistant prose deltas)
 *   - idp_conversation_tool_call_start    (provider began emitting a tool call)
 *   - idp_conversation_progress           (tool-emitted user_visible_message)
 *
 * Room semantics: Frappe's realtime server multiplexes events by doc
 * room — clients must ``emit('doc_subscribe', {doctype, docname})``
 * before they can receive messages published with the
 * ``doctype/docname`` kwargs.  We do that here on every conversation
 * id change and tear down the previous subscription so handlers fire
 * for exactly one conversation at a time.
 */

import { onBeforeUnmount, ref, watch } from 'vue'

import { useSocket } from '@/socket'

const EVENT_NAMES = [
  'idp_conversation_message',
  'idp_conversation_thinking',
  'idp_conversation_tool_start',
  'idp_conversation_tool_end',
  'idp_conversation_error',
  'idp_conversation_complete',
  // Phase 30
  'idp_conversation_token',
  'idp_conversation_tool_call_start',
  'idp_conversation_progress',
]

export function useConversationRealtime(conversationIdRef, handlers = {}) {
  const { getSocket, isConnected } = useSocket()
  const connected = ref(false)
  const subscriptions = []
  let currentDoc = null

  function unsubscribeAll() {
    const sock = getSocket()
    while (subscriptions.length) {
      const { event, fn } = subscriptions.pop()
      try {
        if (sock && typeof sock.off === 'function') sock.off(event, fn)
      } catch (e) {
        // swallow
      }
    }
    if (sock && currentDoc) {
      try {
        sock.emit('doc_unsubscribe', currentDoc.doctype, currentDoc.docname)
      } catch (e) {
        // Older frappe builds ignore unknown events — safe.
      }
    }
    currentDoc = null
    connected.value = false
  }

  function joinRoom(sock, id) {
    // Frappe accepts both ``(doctype, docname)`` positional emits and
    // ``{doctype, docname}`` object emits across versions.  Send both
    // so we work against v14 and v15 without sniffing.
    try {
      sock.emit('doc_subscribe', 'IDP Conversation', id)
    } catch (e) {
      /* ignore */
    }
    try {
      sock.emit('doc_subscribe', { doctype: 'IDP Conversation', docname: id })
    } catch (e) {
      /* ignore */
    }
    currentDoc = { doctype: 'IDP Conversation', docname: id }
  }

  function subscribe(id) {
    unsubscribeAll()
    if (!id) return
    const sock = getSocket()
    if (!sock || typeof sock.on !== 'function') return

    joinRoom(sock, id)

    // If the socket reconnects mid-conversation we need to re-join the
    // doc room — Frappe's server forgets subscriptions on disconnect.
    const onReconnect = () => {
      if (currentDoc) joinRoom(sock, currentDoc.docname)
    }
    sock.on('connect', onReconnect)
    subscriptions.push({ event: 'connect', fn: onReconnect })

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
      sock.on(event, fn)
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

  // Re-bind when the underlying socket reconnects after being torn
  // down (e.g. network restore in ``socket.js``) — the previous
  // ``sock`` reference is stale after that.
  watch(isConnected, (now, prev) => {
    if (now && !prev && conversationIdRef && conversationIdRef.value) {
      subscribe(conversationIdRef.value)
    }
  })

  onBeforeUnmount(() => {
    unsubscribeAll()
  })

  return { connected }
}
