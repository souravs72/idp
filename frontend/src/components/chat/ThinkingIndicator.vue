<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div
    v-if="visible"
    class="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200"
  >
    <span class="flex gap-1" aria-hidden="true">
      <span class="dot" />
      <span class="dot" style="animation-delay: 0.15s" />
      <span class="dot" style="animation-delay: 0.3s" />
    </span>
    <span>{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useConversationStore } from '@/stores/conversation'

const store = useConversationStore()

const visible = computed(
  () =>
    store.agentState.running ||
    store.agentState.thinking ||
    !!store.agentState.currentTool,
)

const label = computed(() => {
  const s = store.agentState
  if (s.currentTool) {
    return `Running tool: ${s.currentTool}…`
  }
  if (s.thinking) {
    const iter = s.iteration ? ` (iteration ${s.iteration})` : ''
    return `Assistant is thinking${iter}…`
  }
  if (s.running) {
    return 'Working…'
  }
  return ''
})
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
</style>
