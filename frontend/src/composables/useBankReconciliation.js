// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { ref, computed } from 'vue'
import {
  extractBankStatement,
  reconcileBankStatement,
} from '@/utils/api'

/**
 * Composable for the Phase 12 bank-statement pipeline.
 *
 * Stage 1: `extract(fileUrl, language)` — parses a bank statement PDF/image
 *          into a structured transaction list.
 * Stage 2: `reconcile(bankAccount, company)` — matches the parsed
 *          transactions against Payment Entries in ERPNext.
 */
export function useBankReconciliation() {
  const statement = ref(null)
  const reconciliation = ref(null)

  const extracting = ref(false)
  const reconciling = ref(false)
  const error = ref(null)

  const processingTimeMs = ref(0)

  const transactions = computed(() => statement.value?.transactions || [])
  const issues = computed(() => statement.value?.issues || [])

  const counts = computed(() => reconciliation.value?.counts || null)
  const matched = computed(() => reconciliation.value?.matched || [])
  const partiallyMatched = computed(
    () => reconciliation.value?.partially_matched || [],
  )
  const multipleMatches = computed(
    () => reconciliation.value?.multiple_matches || [],
  )
  const unmatched = computed(() => reconciliation.value?.unmatched || [])
  const summary = computed(() => reconciliation.value?.summary || '')

  async function extract({ fileUrl, language }) {
    extracting.value = true
    error.value = null
    statement.value = null
    reconciliation.value = null

    try {
      const response = await extractBankStatement({ fileUrl, language })
      const result = response.message || response
      if (result.success) {
        statement.value = result.statement
        processingTimeMs.value = result.processing_time_ms
        return result
      }
      error.value = result.error || 'Bank statement extraction failed'
      return null
    } catch (err) {
      error.value = err.message || 'Bank statement extraction failed'
      return null
    } finally {
      extracting.value = false
    }
  }

  async function reconcile({ bankAccount, company }) {
    if (!statement.value) {
      error.value = 'No statement parsed — run extract() first.'
      return null
    }
    reconciling.value = true
    error.value = null
    reconciliation.value = null

    try {
      const response = await reconcileBankStatement({
        bankAccount,
        transactions: statement.value.transactions,
        company,
      })
      const result = response.message || response
      if (result.success) {
        reconciliation.value = result.reconciliation
        return result
      }
      error.value = result.error || 'Reconciliation failed'
      return null
    } catch (err) {
      error.value = err.message || 'Reconciliation failed'
      return null
    } finally {
      reconciling.value = false
    }
  }

  function reset() {
    statement.value = null
    reconciliation.value = null
    processingTimeMs.value = 0
    error.value = null
  }

  return {
    statement,
    reconciliation,
    extracting,
    reconciling,
    error,
    processingTimeMs,
    transactions,
    issues,
    counts,
    matched,
    partiallyMatched,
    multipleMatches,
    unmatched,
    summary,
    extract,
    reconcile,
    reset,
  }
}
