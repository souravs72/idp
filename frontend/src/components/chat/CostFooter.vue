<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
Phase 31 G12 — persistent cost / token / latency chip docked at the
bottom of the chat surface.  Subscribes to the Pinia conversation
store (``currentDetail``) and re-renders within 1s of stream
completion since the underlying ``total_tokens_used`` /
``estimated_cost_usd`` are refreshed by the realtime ``message``
event.

Settings gate: ``IDP Settings.enable_cost_footer`` — when off the
component renders nothing so the user sees the legacy plain footer.
-->

<template>
  <div
    v-if="visible"
    class="flex items-center justify-between gap-3 border-t border-gray-200 bg-white px-4 py-1 text-[11px] text-gray-600 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400"
    aria-label="Conversation cost summary"
  >
    <div class="flex items-center gap-3">
      <span class="inline-flex items-center gap-1" :title="`${tokens} total tokens`">
        <span aria-hidden="true">🪙</span>
        <span>{{ tokensLabel }}</span>
      </span>
      <span v-if="cost > 0">${{ costLabel }}</span>
      <span v-if="messageCount">· {{ messageCount }} msg</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useConversationStore } from '@/stores/conversation'
import { useSettings } from '@/composables/useSettings'

const store = useConversationStore()
const { settings } = useSettings()

const enabled = computed(() => {
  const v = settings.value?.enable_cost_footer
  if (v == null) return true
  return !!Number(v)
})

const tokens = computed(() => store.currentDetail?.total_tokens_used || 0)
const cost = computed(() => Number(store.currentDetail?.estimated_cost_usd || 0))
const messageCount = computed(() => store.currentDetail?.message_count || 0)

const visible = computed(() => enabled.value && !!store.currentId)

const tokensLabel = computed(() => {
  const n = tokens.value || 0
  if (n >= 1000) {
    return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k tokens`
  }
  return `${n} tokens`
})

const costLabel = computed(() => {
  const n = cost.value || 0
  if (n < 0.01) return n.toFixed(4)
  return n.toFixed(3)
})
</script>
