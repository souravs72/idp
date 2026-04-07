// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { ref, computed } from 'vue'
import { extractDocument, createDocument, getMissingMasters } from '@/utils/api'

/**
 * Composable for extraction and document creation state.
 */
export function useExtraction() {
  const extractedData = ref(null)
  const unmappedFields = ref([])
  const confidenceScores = ref({})
  const validation = ref(null)
  const confidence = ref(null)
  const processingTimeMs = ref(0)

  const extracting = ref(false)
  const creating = ref(false)
  const extractionError = ref(null)
  const creationError = ref(null)
  const creationResult = ref(null)

  const missingMasters = ref([])
  const checkingMasters = ref(false)

  const isValid = computed(() => validation.value?.is_valid ?? false)

  const validationErrors = computed(() => validation.value?.errors || [])

  const validationWarnings = computed(() => validation.value?.warnings || [])

  async function extract({ fileUrl, targetDoctype, company, language }) {
    extracting.value = true
    extractionError.value = null
    extractedData.value = null
    validation.value = null

    try {
      const response = await extractDocument({
        fileUrl,
        targetDoctype,
        company,
        language,
      })
      const result = response.message || response

      if (result.success) {
        extractedData.value = result.extracted_data
        unmappedFields.value = result.unmapped_fields || []
        confidenceScores.value = result.confidence_scores || {}
        validation.value = result.validation
        confidence.value = result.confidence
        processingTimeMs.value = result.processing_time_ms
        return result
      } else {
        extractionError.value = result.error || 'Extraction failed'
        return null
      }
    } catch (err) {
      extractionError.value = err.message || 'Extraction failed'
      return null
    } finally {
      extracting.value = false
    }
  }

  async function checkMissingMasters({ targetDoctype, company }) {
    if (!extractedData.value) return []
    checkingMasters.value = true
    try {
      const response = await getMissingMasters({
        targetDoctype,
        extractedData: extractedData.value,
        company,
      })
      const result = response.message || response
      missingMasters.value = result.missing || []
      return missingMasters.value
    } catch (err) {
      missingMasters.value = []
      return []
    } finally {
      checkingMasters.value = false
    }
  }

  async function create({
    targetDoctype,
    company,
    createMissingMasters: autoCreate,
    itemDefaults,
  }) {
    if (!extractedData.value) {
      creationError.value = 'No extracted data available'
      return null
    }

    creating.value = true
    creationError.value = null
    creationResult.value = null

    try {
      const response = await createDocument({
        targetDoctype,
        extractedData: extractedData.value,
        company,
        createMissingMasters: autoCreate,
        itemDefaults,
      })
      const result = response.message || response

      if (result.success) {
        creationResult.value = result
        return result
      } else {
        creationError.value = result.error || 'Creation failed'
        if (result.error_type === 'MissingMasterError') {
          missingMasters.value = result.details?.missing || []
        }
        return null
      }
    } catch (err) {
      creationError.value = err.message || 'Creation failed'
      return null
    } finally {
      creating.value = false
    }
  }

  function updateHeaderField(fieldname, value) {
    if (extractedData.value?.header) {
      extractedData.value.header[fieldname] = value
    }
  }

  function updateItemField(rowIndex, fieldname, value) {
    if (extractedData.value?.items?.[rowIndex]) {
      extractedData.value.items[rowIndex][fieldname] = value
    }
  }

  function reset() {
    extractedData.value = null
    unmappedFields.value = []
    confidenceScores.value = {}
    validation.value = null
    confidence.value = null
    processingTimeMs.value = 0
    extractionError.value = null
    creationError.value = null
    creationResult.value = null
    missingMasters.value = []
  }

  return {
    extractedData,
    unmappedFields,
    confidenceScores,
    validation,
    confidence,
    processingTimeMs,
    extracting,
    creating,
    extractionError,
    creationError,
    creationResult,
    missingMasters,
    checkingMasters,
    isValid,
    validationErrors,
    validationWarnings,
    extract,
    checkMissingMasters,
    create,
    updateHeaderField,
    updateItemField,
    reset,
  }
}
