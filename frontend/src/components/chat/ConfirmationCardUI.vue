<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div
    class="rounded-lg border border-amber-300 bg-amber-50 p-4 shadow-sm dark:border-amber-700 dark:bg-amber-950"
  >
    <div class="mb-3 flex items-start justify-between gap-3">
      <div>
        <div class="text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
          Confirmation required
        </div>
        <div class="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {{ card.title || `Create ${card.doctype || 'document'}` }}
        </div>
        <div
          v-if="card.subtitle"
          class="text-xs text-gray-600 dark:text-gray-400"
        >
          {{ card.subtitle }}
        </div>
      </div>
      <span
        class="rounded bg-amber-200 px-2 py-0.5 text-[10px] font-mono uppercase text-amber-900 dark:bg-amber-800 dark:text-amber-100"
      >
        v{{ card.version || '?' }}
      </span>
    </div>

    <!-- Header fields -->
    <div v-if="headerFields.length" class="mb-4 grid gap-3 sm:grid-cols-2">
      <div v-for="field in headerFields" :key="field.fieldname">
        <label class="text-[11px] font-medium text-gray-600 dark:text-gray-400">
          {{ field.label || field.fieldname }}
        </label>
        <input
          v-if="!editing"
          class="mt-1 w-full rounded border border-gray-200 bg-white px-2 py-1 text-sm text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
          :value="field.value ?? ''"
          disabled
        />
        <input
          v-else
          v-model="edits.header[field.fieldname]"
          class="mt-1 w-full rounded border border-gray-300 bg-white px-2 py-1 text-sm focus:border-amber-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900"
        />
      </div>
    </div>

    <!-- Items table -->
    <div v-if="itemsBlock.rows?.length" class="mb-4">
      <div
        class="mb-1 flex items-center justify-between text-xs font-medium text-gray-700 dark:text-gray-300"
      >
        <span>
          Items
          <span class="text-gray-500">
            ({{ itemsTotal }} row{{ itemsTotal === 1 ? '' : 's' }})
          </span>
        </span>
        <div v-if="itemsTotal > pageSize" class="flex items-center gap-2">
          <button
            class="rounded border border-gray-300 px-2 py-0.5 text-[11px] disabled:opacity-50 dark:border-gray-700"
            :disabled="page <= 1 || itemsLoading"
            @click="loadPage(page - 1)"
          >
            Prev
          </button>
          <span class="text-[11px] text-gray-500">
            Page {{ page }} / {{ totalPages }}
          </span>
          <button
            class="rounded border border-gray-300 px-2 py-0.5 text-[11px] disabled:opacity-50 dark:border-gray-700"
            :disabled="page >= totalPages || itemsLoading"
            @click="loadPage(page + 1)"
          >
            Next
          </button>
        </div>
      </div>
      <div class="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
        <table class="w-full text-xs">
          <thead class="bg-gray-100 dark:bg-gray-800">
            <tr>
              <th
                v-for="col in itemColumns"
                :key="col"
                class="px-2 py-1 text-left font-medium text-gray-700 dark:text-gray-200"
              >
                {{ col }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, idx) in displayItems"
              :key="idx"
              class="border-t border-gray-100 dark:border-gray-700"
            >
              <td
                v-for="col in itemColumns"
                :key="col"
                class="px-2 py-1 text-gray-700 dark:text-gray-300"
              >
                {{ formatCell(row?.data?.[col] ?? row?.[col]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Taxes table -->
    <div v-if="taxRows.length" class="mb-4">
      <div class="mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">
        Taxes
      </div>
      <div class="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
        <table class="w-full text-xs">
          <thead class="bg-gray-100 dark:bg-gray-800">
            <tr>
              <th class="px-2 py-1 text-left">Account</th>
              <th class="px-2 py-1 text-right">Rate</th>
              <th class="px-2 py-1 text-right">Tax amount</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, idx) in taxRows"
              :key="idx"
              class="border-t border-gray-100 dark:border-gray-700"
            >
              <td class="px-2 py-1 text-gray-700 dark:text-gray-300">
                <span v-if="!editing">
                  {{ row.erpnext_account || row.extracted?.account || '—' }}
                </span>
                <input
                  v-else
                  v-model="edits.account_mappings[idx]"
                  class="w-full rounded border border-gray-300 bg-white px-1 py-0.5 text-xs dark:border-gray-700 dark:bg-gray-900"
                  :placeholder="row.extracted?.account || 'Account'"
                />
              </td>
              <td class="px-2 py-1 text-right">
                {{ formatCell(row.extracted?.rate) }}
              </td>
              <td class="px-2 py-1 text-right">
                {{ formatCell(row.extracted?.tax_amount) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Warnings -->
    <div v-if="warningList.length" class="mb-4 rounded bg-yellow-100 p-2 text-xs text-yellow-900 dark:bg-yellow-900 dark:text-yellow-100">
      <div class="mb-1 font-semibold">Warnings</div>
      <ul class="list-inside list-disc space-y-0.5">
        <li v-for="(w, idx) in warningList" :key="idx">{{ w }}</li>
      </ul>
    </div>

    <!-- Revalidation warnings (after edits / submit) -->
    <div v-if="revalidationWarnings.length" class="mb-4 rounded bg-orange-100 p-2 text-xs text-orange-900 dark:bg-orange-900 dark:text-orange-100">
      <div class="mb-1 font-semibold">Revalidation</div>
      <ul class="list-inside list-disc space-y-0.5">
        <li v-for="(w, idx) in revalidationWarnings" :key="idx">{{ w }}</li>
      </ul>
    </div>

    <!-- Action buttons -->
    <div class="flex flex-wrap gap-2">
      <button
        v-for="action in actions"
        :key="action.id"
        :disabled="busy"
        class="rounded px-3 py-1.5 text-xs font-medium disabled:opacity-50"
        :class="actionStyle(action)"
        @click="invoke(action.id)"
      >
        {{ action.label || action.id }}
      </button>
    </div>

    <div v-if="lastError" class="mt-2 text-xs text-red-700 dark:text-red-400">
      {{ lastError }}
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useAgent } from '@/composables/useAgent'
import { getCardItemsPage } from '@/utils/api'
import { useConversationStore } from '@/stores/conversation'

const props = defineProps({
  message: { type: Object, required: true },
})
const emit = defineEmits(['confirmed'])

const store = useConversationStore()
const { confirm, busy: agentBusy } = useAgent()

const card = computed(() => parseJSON(props.message.rendered_card_payload) || {})
const headerFields = computed(() => {
  const h = card.value.header
  if (Array.isArray(h)) return h.filter((f) => f && typeof f === 'object')
  return []
})
const itemsBlock = computed(() => card.value.items || {})
const itemsTotal = computed(() => itemsBlock.value.total || (itemsBlock.value.rows || []).length || 0)
const pageSize = computed(() => itemsBlock.value.page_size || 10)
const totalPages = computed(() =>
  Math.max(1, Math.ceil(itemsTotal.value / pageSize.value)),
)
const page = ref(1)
const itemsLoading = ref(false)
const fetchedRows = ref(null)

const displayItems = computed(() => {
  if (page.value === 1 || !fetchedRows.value) {
    return itemsBlock.value.rows || []
  }
  return fetchedRows.value
})
const itemColumns = computed(() => {
  const sample = displayItems.value?.[0]
  const data = sample?.data || sample || {}
  return Object.keys(data || {}).slice(0, 8)
})

const taxRows = computed(() => {
  const t = card.value.taxes
  if (!t || !Array.isArray(t.rows)) return []
  return t.rows.filter((r) => r && typeof r === 'object')
})

const warningList = computed(() => {
  const w = card.value.warnings
  if (!Array.isArray(w)) return []
  return w
    .map((x) => (typeof x === 'string' ? x : x?.message))
    .filter(Boolean)
})

const actions = computed(() => {
  const a = card.value.actions
  if (Array.isArray(a)) {
    return a.filter((x) => x && x.id)
  }
  // sensible fallback set
  return [
    { id: 'submit', label: 'Submit' },
    { id: 'save_draft', label: 'Save Draft' },
    { id: 'edit', label: 'Edit' },
    { id: 'cancel', label: 'Cancel' },
  ]
})

const editing = ref(false)
const edits = ref({
  header: {},
  account_mappings: {},
  // items / taxes left untouched unless user explicitly edits
})
const lastError = ref(null)
const revalidationWarnings = ref([])
const busy = computed(() => agentBusy.value)

function actionStyle(a) {
  switch (a.id) {
    case 'submit':
      return 'bg-amber-600 text-white hover:bg-amber-700'
    case 'save_draft':
      return 'bg-gray-700 text-white hover:bg-gray-800'
    case 'cancel':
      return 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-200'
    case 'edit':
      return 'bg-blue-600 text-white hover:bg-blue-700'
    default:
      return 'bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-100'
  }
}

function parseJSON(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch (_) {
    return null
  }
}

function formatCell(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

async function loadPage(target) {
  if (target < 1 || target > totalPages.value || itemsLoading.value) return
  if (target === 1) {
    page.value = 1
    fetchedRows.value = null
    return
  }
  itemsLoading.value = true
  try {
    const out = await getCardItemsPage({
      conversationId: store.currentId,
      messageId: props.message.name,
      page: target,
      pageSize: pageSize.value,
    })
    fetchedRows.value = out?.rows || []
    page.value = target
  } catch (err) {
    lastError.value = err?.message || String(err)
  } finally {
    itemsLoading.value = false
  }
}

async function invoke(action) {
  lastError.value = null
  if (action === 'edit') {
    editing.value = !editing.value
    return
  }
  try {
    const editsPayload =
      editing.value &&
      (Object.keys(edits.value.header).length ||
        Object.keys(edits.value.account_mappings).length)
        ? buildEditsPayload()
        : null
    const result = await confirm({
      messageId: props.message.name,
      action,
      edits: editsPayload,
      sendFollowUp: action === 'submit',
    })
    revalidationWarnings.value = result?.revalidation_warnings || []
    emit('confirmed', { action, result })
  } catch (err) {
    lastError.value = err?.message || String(err)
  }
}

function buildEditsPayload() {
  const out = {}
  if (Object.keys(edits.value.header).length) out.header = { ...edits.value.header }
  if (Object.keys(edits.value.account_mappings).length) {
    out.account_mappings = { ...edits.value.account_mappings }
  }
  return out
}
</script>
