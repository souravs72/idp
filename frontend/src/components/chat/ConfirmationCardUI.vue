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
      <div class="flex items-center gap-2">
        <span
          v-if="card.submitted"
          class="rounded bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white dark:bg-emerald-500 dark:text-white"
        >
          Submitted
        </span>
        <span
          v-else-if="card.draft_saved"
          class="rounded bg-gray-700 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white dark:bg-gray-200 dark:text-gray-900"
        >
          Draft Saved
        </span>
        <span
          class="rounded bg-amber-200 px-2 py-0.5 text-[10px] font-mono uppercase text-amber-900 dark:bg-amber-800 dark:text-amber-100"
        >
          v{{ card.version || '?' }}
        </span>
      </div>
    </div>

    <!-- Header fields -->
    <div v-if="headerFields.length" class="mb-4 grid gap-3 sm:grid-cols-2">
      <div v-for="field in headerFields" :key="field.fieldname">
        <label class="text-[11px] font-medium text-gray-600 dark:text-gray-400">
          {{ formatLabel(field) }}
        </label>
        <input
          v-if="!editing || field.editable === false"
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

    <!-- Items table (Phase 24 §24.0) -->
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
      <ItemMappingTable
        :rows="displayItems"
        :editing="editing"
        @edit="onItemEdit"
        @edit-stock="onItemStockEdit"
      />
    </div>

    <!-- Taxes table (Phase 24 §24.4) -->
    <div v-if="taxRows.length" class="mb-4">
      <div class="mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">
        Taxes
      </div>
      <TaxMappingTable
        :rows="taxRows"
        :editing="editing"
        :company="card.company || null"
        @edit="onTaxEdit"
      />
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
    <div v-if="actions.length" class="flex flex-wrap gap-2">
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
    <div
      v-else-if="card.submitted && card.created_doc"
      class="rounded bg-emerald-50 px-3 py-2 text-[11px] text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
    >
      Submitted as
      <a
        v-if="card.created_doc.url"
        :href="card.created_doc.url"
        target="_blank"
        rel="noopener"
        class="underline"
      >
        {{ card.created_doc.doctype }} {{ card.created_doc.name }}
      </a>
      <span v-else>{{ card.created_doc.doctype }} {{ card.created_doc.name }}</span>.
    </div>
    <div
      v-else-if="card.draft_saved && card.created_doc"
      class="rounded bg-gray-100 px-3 py-2 text-[11px] text-gray-700 dark:bg-gray-800 dark:text-gray-200"
    >
      Saved as draft
      <a
        v-if="card.created_doc.url"
        :href="card.created_doc.url"
        target="_blank"
        rel="noopener"
        class="underline"
      >
        {{ card.created_doc.doctype }} {{ card.created_doc.name }}
      </a>
      <span v-else>{{ card.created_doc.doctype }} {{ card.created_doc.name }}</span>.
    </div>
    <div
      v-else-if="card.draft_saved"
      class="rounded bg-gray-100 px-3 py-2 text-[11px] text-gray-600 dark:bg-gray-800 dark:text-gray-300"
    >
      This proposal is parked as a draft. Re-open it to submit later.
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
import ItemMappingTable from './ItemMappingTable.vue'
import TaxMappingTable from './TaxMappingTable.vue'

const props = defineProps({
  message: { type: Object, required: true },
})
const emit = defineEmits(['confirmed'])

const store = useConversationStore()
const { confirm, busy: agentBusy } = useAgent()

const card = computed(() => parseJSON(props.message.rendered_card_payload) || {})

// Hide only the noisy mirror fields the user explicitly called out:
// party_name duplicates supplier/customer, conversion_rate is constant
// when currency==company currency, and base_total / base_net_total /
// base_grand_total mirror the totals already shown alongside the card.
// We deliberately keep `total`, `net_total`, `grand_total`, etc. so
// the user can review the headline numbers without scrolling.
const HIDDEN_HEADER_FIELDS = new Set([
  'supplier_name',
  'customer_name',
  'party_name',
  'conversion_rate',
  'plc_conversion_rate',
  'base_total',
  'base_net_total',
  'base_grand_total',
  'base_taxes_and_charges',
  'base_total_taxes_and_charges',
  'base_rounded_total',
  'base_rounding_adjustment',
  'base_in_words',
])

function isHiddenHeaderField(fieldname) {
  if (!fieldname) return true
  return HIDDEN_HEADER_FIELDS.has(fieldname)
}

const headerFields = computed(() => {
  const h = card.value.header
  if (!Array.isArray(h)) return []
  return h.filter(
    (f) => f && typeof f === 'object' && !isHiddenHeaderField(f.fieldname),
  )
})

// Render a fieldname like ``posting_date`` as ``Posting Date``.  Uses
// the server-supplied ``label`` when it isn't just the fieldname echoed
// back, otherwise falls back to title-casing the snake_case field.
function formatLabel(field) {
  const fieldname = field?.fieldname || ''
  const label = field?.label || ''
  if (label && label !== fieldname) return label
  if (!fieldname) return ''
  return fieldname
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}
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
  // The server is authoritative for the action set.  When the card has
  // been confirmed (submit / save_draft) the server stores
  // ``actions: []`` to lock the card read-only — never inject a default
  // four-button set here or the card will re-render as actionable and
  // appear as a duplicate confirmation prompt (Phase 24 fix).
  const a = card.value.actions
  if (Array.isArray(a)) {
    return a.filter((x) => x && x.id)
  }
  return []
})

const editing = ref(false)
const edits = ref({
  header: {},
  item_mappings: {}, // {row_index: erpnext_item}
  account_mappings: {}, // {row_index: erpnext_account}
  item_stock_overrides: {}, // {row_index: bool}
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
    if (!editing.value) {
      // Seed edits.header from current header values so toggling Edit
      // shows the extracted data in the inputs (Phase 24 fix).
      const seeded = {}
      for (const f of headerFields.value) {
        if (f && f.fieldname) {
          seeded[f.fieldname] = f.value ?? ''
        }
      }
      edits.value.header = seeded
    }
    editing.value = !editing.value
    return
  }

  if (action === 'cancel') {
    // Phase 24 — Cancel resets all pending edits to the extracted data
    // currently held in the card payload.  No backend call is made;
    // the persisted card payload is the source of truth and is never
    // mutated on cancel.
    edits.value = {
      header: {},
      item_mappings: {},
      account_mappings: {},
      item_stock_overrides: {},
    }
    revalidationWarnings.value = []
    editing.value = false
    emit('confirmed', { action, result: null })
    return
  }

  try {
    const hasEdits =
      Object.keys(edits.value.header).length ||
      Object.keys(edits.value.item_mappings).length ||
      Object.keys(edits.value.account_mappings).length ||
      Object.keys(edits.value.item_stock_overrides).length
    const editsPayload =
      (editing.value && hasEdits) ||
      // Mapping/stock toggles are always live, even outside Edit mode.
      Object.keys(edits.value.item_mappings).length ||
      Object.keys(edits.value.account_mappings).length ||
      Object.keys(edits.value.item_stock_overrides).length
        ? buildEditsPayload()
        : null
    const result = await confirm({
      messageId: props.message.name,
      action,
      edits: editsPayload,
    })
    revalidationWarnings.value = result?.revalidation_warnings || []
    // Surface a server-side error envelope (e.g. insert failed) onto
    // the card itself in addition to the chat.
    if (result?.error?.friendly_message) {
      lastError.value = result.error.friendly_message
    }
    // After a successful submit/save_draft the action set is cleared
    // server-side, so the card re-renders read-only.  Drop edit mode
    // locally too in case the user had it open.
    editing.value = false
    emit('confirmed', { action, result })
  } catch (err) {
    lastError.value = err?.message || String(err)
  }
}

function buildEditsPayload() {
  const out = {}
  if (Object.keys(edits.value.header).length) out.header = { ...edits.value.header }
  if (Object.keys(edits.value.item_mappings).length) {
    out.item_mappings = { ...edits.value.item_mappings }
  }
  if (Object.keys(edits.value.account_mappings).length) {
    out.account_mappings = { ...edits.value.account_mappings }
  }
  if (Object.keys(edits.value.item_stock_overrides).length) {
    out.item_stock_overrides = { ...edits.value.item_stock_overrides }
  }
  return out
}

function onItemEdit({ index, value }) {
  if (index == null) return
  edits.value.item_mappings = {
    ...edits.value.item_mappings,
    [index]: value,
  }
}

function onItemStockEdit({ index, value }) {
  if (index == null) return
  edits.value.item_stock_overrides = {
    ...edits.value.item_stock_overrides,
    [index]: !!value,
  }
}

function onTaxEdit({ index, value }) {
  if (index == null) return
  edits.value.account_mappings = {
    ...edits.value.account_mappings,
    [index]: value,
  }
}
</script>
