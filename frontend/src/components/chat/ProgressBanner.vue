<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 30 — Progress Banner

  Surfaces the most-recent ``user_visible_message`` emitted by a tool
  (e.g. "Reading invoice.pdf…", "Read 3 page(s); analysing…").
  Disappears automatically once a new ``idp_conversation_message`` lands
  for the streaming turn, or when the run completes / errors out.
-->

<template>
  <transition name="fade">
    <div
      v-if="visible"
      class="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
      role="status"
      aria-live="polite"
    >
      <span class="flex gap-1" aria-hidden="true">
        <span class="dot" />
        <span class="dot" style="animation-delay: 0.15s" />
        <span class="dot" style="animation-delay: 0.3s" />
      </span>
      <span class="truncate">{{ label }}</span>
    </div>
  </transition>
</template>

<script setup>
import { computed } from 'vue'
import { useConversationStore } from '@/stores/conversation'

const store = useConversationStore()

const visible = computed(() => {
  if (!store.progressState?.message) return false
  // Hide once the run is no longer active (complete / error path).
  if (!store.agentState.running && !store.streamingState.active) return false
  return true
})

const label = computed(() => store.progressState.message || '')
</script>

<style scoped>
.dot {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background: currentColor;
  display: inline-block;
  animation: idp-bounce 1s infinite;
}
@keyframes idp-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
