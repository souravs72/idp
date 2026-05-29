<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<!--
  UpdateCard renderer for the update_document tool.

  Payload shape (idp/tools/update_document.py, dry_run=true):
    {
      card_type: "UpdateCard",
      doctype: "Purchase Invoice",
      name: "PINV-00042",
      diff: [{fieldname, before, after, changed}, ...],
      reason: "free-text or null",
      summary: "Update ...: N fields will change."
    }

  Two-step confirmation: clicking "Confirm update" posts a follow-up
  message that re-invokes the tool with dry_run=false.
-->

<template>
  <div
    class="idp-update-card rounded-lg border border-violet-300 bg-violet-50 p-4 shadow-sm dark:border-violet-700 dark:bg-violet-950"
    role="region"
    :aria-label="`Update card: ${card.doctype || 'document'} ${card.name || ''}`"
  >
    <div class="mb-3 flex items-start gap-2">
      <span aria-hidden="true" class="text-base leading-none">✏️</span>
      <div>
        <div
          class="text-xs font-semibold uppercase tracking-wide text-violet-800 dark:text-violet-200"
        >
          Pending update
        </div>
        <div class="mt-0.5 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {{ card.doctype }} · {{ card.name }}
        </div>
        <div v-if="card.summary" class="mt-0.5 text-xs text-gray-600 dark:text-gray-400">
          {{ card.summary }}
        </div>
        <div v-if="card.reason" class="mt-0.5 text-[11px] italic text-gray-500 dark:text-gray-400">
          Reason: {{ card.reason }}
        </div>
      </div>
    </div>

    <!-- Pre-flight warnings (e.g. ERPNext's Repost Accounting Ledger
         guard) surfaced before the user clicks Confirm Update.  Apply
         will likely fail until the warning is resolved. -->
    <div
      v-if="warnings.length"
      class="mb-3 rounded border border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
      role="alert"
    >
      <div class="mb-1 flex items-center gap-1 font-semibold uppercase tracking-wide">
        <span aria-hidden="true">⚠️</span> Pre-flight check
      </div>
      <ul class="list-disc space-y-1 pl-5">
        <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
      </ul>
    </div>

    <div v-if="noChanges" class="rounded border border-gray-200 bg-white px-3 py-2 text-xs text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
      No effective changes — every supplied field already matches the
      current value.  Nothing to confirm.
    </div>

    <div v-else class="overflow-x-auto rounded border border-gray-300 dark:border-gray-600">
      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th
              scope="col"
              class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            >
              Field
            </th>
            <th
              scope="col"
              class="border border-gray-300 bg-gray-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            >
              Before
            </th>
            <th
              scope="col"
              class="border border-gray-300 bg-violet-100 px-2 py-1 text-left font-semibold text-gray-700 dark:border-gray-600 dark:bg-violet-900 dark:text-gray-100"
            >
              After
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in diff"
            :key="row.fieldname"
            :class="rowBg(row)"
          >
            <td class="border border-gray-300 px-2 py-1.5 font-mono text-[11px] text-gray-700 dark:border-gray-600 dark:text-gray-300">
              {{ row.fieldname }}
            </td>
            <td class="border border-gray-300 px-2 py-1.5 text-gray-700 dark:border-gray-600 dark:text-gray-300">
              {{ formatValue(row.before) }}
            </td>
            <td
              class="border border-gray-300 px-2 py-1.5 text-gray-700 dark:border-gray-600 dark:text-gray-300"
              :class="row.changed ? 'font-semibold' : ''"
            >
              {{ formatValue(row.after) }}
              <span
                v-if="row.resolved_from"
                class="ml-1 inline-block rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-800 dark:bg-violet-900 dark:text-violet-200"
                :title="`You supplied “${row.resolved_from}” — resolved to the canonical name above.`"
              >
                resolved from “{{ row.resolved_from }}”
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-2">
      <button
        type="button"
        class="rounded bg-violet-600 px-3 py-1 text-xs font-medium text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="noChanges || agentBusy || confirmed"
        @click="onConfirm"
      >
        {{ confirmed ? 'Confirmed' : 'Confirm update' }}
      </button>
      <button
        type="button"
        class="rounded border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700"
        :disabled="agentBusy || confirmed"
        @click="onCancel"
      >
        Cancel
      </button>
      <span v-if="status" class="text-[11px] text-gray-600 dark:text-gray-400">
        {{ status }}
      </span>
    </div>

    <div v-if="lastError" class="mt-2 text-xs text-red-700 dark:text-red-400">
      {{ lastError }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useConversationStore } from '@/stores/conversation'
import { confirmUpdateCard, getConversation } from '@/utils/api'

const props = defineProps({
  message: { type: Object, required: true },
})

const store = useConversationStore()
const agentBusy = ref(false)
const lastError = ref(null)
const status = ref(null)
const confirmed = ref(false)

const card = computed(() => {
  const v = props.message.rendered_card_payload
  if (!v) return {}
  if (typeof v === 'object') return v
  try {
    return JSON.parse(v)
  } catch (_) {
    return {}
  }
})

const diff = computed(() => {
  const d = card.value.diff
  return Array.isArray(d) ? d : []
})

const warnings = computed(() => {
  const w = card.value.warnings
  return Array.isArray(w) ? w.filter((s) => typeof s === 'string' && s.trim()) : []
})

const noChanges = computed(
  () => diff.value.length === 0 || diff.value.every((r) => !r.changed),
)

function formatValue(v) {
  if (v == null || v === '') return '—'
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v)
    } catch (_) {
      return String(v)
    }
  }
  return String(v)
}

function rowBg(row) {
  if (!row.changed) {
    return 'odd:bg-white even:bg-gray-50 dark:odd:bg-gray-900 dark:even:bg-gray-800'
  }
  return 'bg-violet-50 dark:bg-violet-950/40'
}

// Conversation id is held by the store — the persisted message dict
// doesn't expose a ``conversation`` field on the frontend shape.
function _conversationId() {
  return (
    store.currentId ||
    props.message.conversation ||
    props.message.parent ||
    null
  )
}

async function onConfirm() {
  if (noChanges.value || agentBusy.value || confirmed.value) return
  const conversationId = _conversationId()
  if (!conversationId) {
    lastError.value = 'No active conversation — reload the page and try again.'
    return
  }
  lastError.value = null
  status.value = 'Applying…'
  agentBusy.value = true
  try {
    const res = await confirmUpdateCard({
      conversationId,
      messageId: props.message.name,
      action: 'apply',
    })
    confirmed.value = true
    if (res && res.success === false) {
      status.value = null
      lastError.value = res.error || 'Update failed'
    } else {
      status.value = 'Applied'
    }
    // Pull the fresh history so the ack message appears even if the
    // realtime socket missed the event.
    try {
      const detail = await getConversation(conversationId)
      store.setCurrent(detail)
    } catch (_) {
      // non-fatal
    }
  } catch (err) {
    lastError.value = err?.message || String(err)
    status.value = null
  } finally {
    agentBusy.value = false
  }
}

async function onCancel() {
  if (agentBusy.value || confirmed.value) return
  const conversationId = _conversationId()
  if (!conversationId) {
    lastError.value = 'No active conversation — reload the page and try again.'
    return
  }
  agentBusy.value = true
  try {
    await confirmUpdateCard({
      conversationId,
      messageId: props.message.name,
      action: 'cancel',
    })
    status.value = 'Update cancelled — nothing was applied.'
    confirmed.value = true
  } catch (err) {
    lastError.value = err?.message || String(err)
  } finally {
    agentBusy.value = false
  }
}
</script>
