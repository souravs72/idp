<!-- Copyright (c) 2026, Sanjay Kumar and contributors -->
<!-- For license information, please see license.txt -->

<template>
  <div class="space-y-6">
    <!-- Statement header -->
    <div
      v-if="statement"
      class="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800"
    >
      <div class="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <div class="text-xs text-gray-500">Account</div>
          <div class="font-medium">{{ statement.account_number || '—' }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Period</div>
          <div class="font-medium">
            {{ statement.statement_period_from || '—' }}
            <span v-if="statement.statement_period_to">
              → {{ statement.statement_period_to }}
            </span>
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Currency</div>
          <div class="font-medium">{{ statement.currency || '—' }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Transactions</div>
          <div class="font-medium">{{ statement.transaction_count }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Opening</div>
          <div class="font-medium">
            {{ formatNumber(statement.opening_balance) }}
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Closing</div>
          <div class="font-medium">
            {{ formatNumber(statement.closing_balance) }}
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Total Debits</div>
          <div class="font-medium text-red-600 dark:text-red-400">
            {{ formatNumber(statement.total_debits) }}
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-500">Total Credits</div>
          <div class="font-medium text-green-600 dark:text-green-400">
            {{ formatNumber(statement.total_credits) }}
          </div>
        </div>
      </div>

      <!-- Issues -->
      <div
        v-if="statement.issues && statement.issues.length > 0"
        class="mt-3 space-y-1"
      >
        <div
          v-for="(issue, i) in statement.issues"
          :key="i"
          class="flex items-start gap-2 text-xs"
          :class="
            issue.severity === 'error'
              ? 'text-red-700 dark:text-red-300'
              : 'text-amber-700 dark:text-amber-300'
          "
        >
          <span class="font-semibold uppercase">{{ issue.severity }}:</span>
          <span>{{ issue.message }}</span>
        </div>
      </div>
    </div>

    <!-- Reconcile controls -->
    <div
      v-if="statement"
      class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700 sm:flex-row sm:items-end"
    >
      <div class="flex-1">
        <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
          Bank Account (ERPNext)
        </label>
        <input
          v-model="localBankAccount"
          type="text"
          placeholder="e.g. HDFC - Current - MEL"
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
        />
      </div>
      <div class="flex-1">
        <label class="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
          Company (optional)
        </label>
        <input
          v-model="localCompany"
          type="text"
          class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800"
        />
      </div>
      <button
        class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        :disabled="!localBankAccount || reconciling"
        @click="onReconcile"
      >
        <span v-if="reconciling">Reconciling…</span>
        <span v-else>Reconcile</span>
      </button>
    </div>

    <!-- Reconciliation summary -->
    <div
      v-if="reconciliation"
      class="rounded-lg border border-gray-200 bg-blue-50 p-4 text-sm text-blue-900 dark:border-gray-700 dark:bg-blue-950 dark:text-blue-100"
    >
      {{ reconciliation.summary }}
    </div>

    <!-- Matched / partial / multiple / unmatched tables -->
    <ReconciliationGroup
      v-if="reconciliation && reconciliation.matched.length"
      title="Matched"
      tone="success"
      :rows="reconciliation.matched"
    />
    <ReconciliationGroup
      v-if="reconciliation && reconciliation.partially_matched.length"
      title="Partially Matched"
      tone="warning"
      :rows="reconciliation.partially_matched"
    />
    <ReconciliationGroup
      v-if="reconciliation && reconciliation.multiple_matches.length"
      title="Multiple Matches — Needs Review"
      tone="warning"
      :rows="reconciliation.multiple_matches"
      show-all-candidates
    />
    <ReconciliationGroup
      v-if="reconciliation && reconciliation.unmatched.length"
      title="Unmatched"
      tone="danger"
      :rows="reconciliation.unmatched"
    />

    <!-- Raw transactions (when not reconciled yet) -->
    <div
      v-if="statement && !reconciliation"
      class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700"
    >
      <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead class="bg-gray-50 dark:bg-gray-800">
          <tr>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Date
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Description
            </th>
            <th class="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">
              Debit
            </th>
            <th class="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">
              Credit
            </th>
            <th class="px-3 py-2 text-right text-xs font-medium uppercase text-gray-500">
              Balance
            </th>
            <th class="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
              Ref
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
          <tr v-for="txn in statement.transactions" :key="txn.row_index">
            <td class="whitespace-nowrap px-3 py-2 text-xs">{{ txn.date }}</td>
            <td class="px-3 py-2 text-xs">{{ txn.description }}</td>
            <td class="whitespace-nowrap px-3 py-2 text-right text-xs text-red-600 dark:text-red-400">
              {{ formatNumber(txn.debit) }}
            </td>
            <td class="whitespace-nowrap px-3 py-2 text-right text-xs text-green-600 dark:text-green-400">
              {{ formatNumber(txn.credit) }}
            </td>
            <td class="whitespace-nowrap px-3 py-2 text-right text-xs">
              {{ formatNumber(txn.balance) }}
            </td>
            <td class="px-3 py-2 text-xs text-gray-500">{{ txn.reference || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import ReconciliationGroup from './ReconciliationGroup.vue'

const props = defineProps({
  statement: { type: Object, default: null },
  reconciliation: { type: Object, default: null },
  reconciling: { type: Boolean, default: false },
  bankAccount: { type: String, default: '' },
  company: { type: String, default: '' },
})

const emit = defineEmits(['reconcile'])

const localBankAccount = ref(props.bankAccount)
const localCompany = ref(props.company)

watch(
  () => props.bankAccount,
  (v) => {
    localBankAccount.value = v
  },
)
watch(
  () => props.company,
  (v) => {
    localCompany.value = v
  },
)

function onReconcile() {
  emit('reconcile', {
    bankAccount: localBankAccount.value,
    company: localCompany.value,
  })
}

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '—'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}
</script>
