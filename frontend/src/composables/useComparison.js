// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { ref, computed } from 'vue'
import { compareDocument, findMatchingRecord } from '@/utils/api'

/**
 * Composable for document comparison state.
 */
export function useComparison() {
  const comparison = ref(null)
  const extractedData = ref(null)
  const processingTimeMs = ref(0)

  const comparing = ref(false)
  const finding = ref(false)
  const comparisonError = ref(null)

  const matchedRecord = ref(null)

  const matches = computed(() => comparison.value?.matches || [])
  const discrepancies = computed(() => comparison.value?.discrepancies || [])
  const missingInDocument = computed(
    () => comparison.value?.missing_in_document || [],
  )
  const missingInRecord = computed(
    () => comparison.value?.missing_in_record || [],
  )
  const itemsComparison = computed(
    () => comparison.value?.items_comparison || [],
  )
  const summary = computed(() => comparison.value?.summary || '')

  async function compare({
    fileUrl,
    compareDoctype,
    compareDocname,
    company,
    language,
  }) {
    comparing.value = true
    comparisonError.value = null
    comparison.value = null

    try {
      const response = await compareDocument({
        fileUrl,
        compareDoctype,
        compareDocname,
        company,
        language,
      })
      const result = response.message || response

      if (result.success) {
        comparison.value = result.comparison
        extractedData.value = result.extracted_data
        processingTimeMs.value = result.processing_time_ms
        return result
      } else {
        comparisonError.value = result.error || 'Comparison failed'
        return null
      }
    } catch (err) {
      comparisonError.value = err.message || 'Comparison failed'
      return null
    } finally {
      comparing.value = false
    }
  }

  async function findMatch({ fileUrl, targetDoctype, company, language }) {
    finding.value = true
    matchedRecord.value = null

    try {
      const response = await findMatchingRecord({
        fileUrl,
        targetDoctype,
        company,
        language,
      })
      const result = response.message || response

      if (result.found) {
        matchedRecord.value = {
          doctype: result.doctype,
          docname: result.docname,
        }
        extractedData.value = result.extracted_data
      }
      return result
    } catch (err) {
      comparisonError.value = err.message || 'Match search failed'
      return null
    } finally {
      finding.value = false
    }
  }

  function reset() {
    comparison.value = null
    extractedData.value = null
    processingTimeMs.value = 0
    comparisonError.value = null
    matchedRecord.value = null
  }

  return {
    comparison,
    extractedData,
    processingTimeMs,
    comparing,
    finding,
    comparisonError,
    matchedRecord,
    matches,
    discrepancies,
    missingInDocument,
    missingInRecord,
    itemsComparison,
    summary,
    compare,
    findMatch,
    reset,
  }
}
