<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  Phase 32 — Reversibility / Undo banner.

  Rendered immediately below the post-confirmation "Submitted as X Y"
  receipt on a ConfirmationCard once the server stamps the message
  with an ``undo`` block (created_doctype, created_docname,
  deadline, window_minutes).

  The banner shows a live countdown so the user always knows how long
  they have, and a single "Undo" button that calls
  ``idp.api.undo.undo_confirmation``.  On success the parent card is
  re-rendered as "Undone" — the rendered_card_payload now carries
  ``card.undone = true`` so the banner disappears on the next prop
  change.
-->

<template>
  <div
    v-if="visible"
    class="mt-2 flex flex-wrap items-center justify-between gap-2 rounded border border-amber-300 bg-amber-100 px-3 py-1.5 text-[11px] text-amber-900 dark:border-amber-700 dark:bg-amber-900 dark:text-amber-100"
    role="status"
  >
    <span>
      You can undo this for
      <span class="font-mono font-semibold">{{ countdownLabel }}</span
      >.
    </span>
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="rounded bg-amber-700 px-2 py-0.5 text-white hover:bg-amber-800 disabled:opacity-50"
        :disabled="busy"
        @click="onUndo"
      >
        {{ busy ? 'Undoing…' : 'Undo' }}
      </button>
      <span v-if="lastError" class="text-red-700 dark:text-red-300">
        {{ lastError }}
      </span>
    </div>
  </div>
  <div
    v-else-if="undone"
    class="mt-2 rounded bg-gray-100 px-3 py-1.5 text-[11px] text-gray-700 dark:bg-gray-800 dark:text-gray-200"
  >
    Undone.
    <span v-if="undoAction === 'deleted'">Draft deleted.</span>
    <span v-else-if="undoAction === 'cancelled'">Document cancelled.</span>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { undoConfirmation } from '@/utils/api'

const props = defineProps({
  message: { type: Object, required: true },
  card: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['undone'])

const busy = ref(false)
const lastError = ref('')
// Re-render the countdown each second by mutating a tick counter.
const tick = ref(0)
let timer = null

onMounted(() => {
  timer = window.setInterval(() => {
    tick.value += 1
  }, 1000)
})
onBeforeUnmount(() => {
  if (timer != null) {
    window.clearInterval(timer)
    timer = null
  }
})

const undo = computed(() => props.card?.undo || null)
const undone = computed(() => !!props.card?.undone)
const undoAction = computed(() => props.card?.undo_result?.action || '')

const remainingSeconds = computed(() => {
  // Read tick so the countdown re-evaluates each second.
  void tick.value
  if (!undo.value?.deadline) return 0
  const deadline = new Date(undo.value.deadline.replace(' ', 'T'))
  const diff = (deadline.getTime() - Date.now()) / 1000
  return Math.max(0, Math.floor(diff))
})

const visible = computed(() => {
  if (undone.value) return false
  if (!undo.value?.deadline) return false
  return remainingSeconds.value > 0
})

const countdownLabel = computed(() => {
  const s = remainingSeconds.value
  const m = Math.floor(s / 60)
  const r = s % 60
  if (m > 0) return `${m}m ${r.toString().padStart(2, '0')}s`
  return `${r}s`
})

async function onUndo() {
  if (busy.value) return
  busy.value = true
  lastError.value = ''
  try {
    const res = await undoConfirmation({ messageId: props.message.name })
    emit('undone', res)
  } catch (err) {
    const detail =
      err?.exception ||
      err?.message ||
      err?._server_messages ||
      'Undo failed.'
    lastError.value = String(detail)
  } finally {
    busy.value = false
  }
}
</script>
