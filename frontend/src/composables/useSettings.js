// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { ref } from 'vue'
import { fetchSettings } from '@/utils/api'

const settings = ref(null)
const loading = ref(false)
const error = ref(null)

/**
 * Composable for IDP settings state.
 * Settings are fetched once and cached for the session.
 */
export function useSettings() {
  async function load() {
    if (settings.value) return settings.value
    loading.value = true
    error.value = null
    try {
      const result = await fetchSettings()
      settings.value = result.message || result
      return settings.value
    } catch (err) {
      error.value = err.message || 'Failed to load settings'
      throw err
    } finally {
      loading.value = false
    }
  }

  function getSupportedDoctypes() {
    return settings.value?.supported_doctypes || []
  }

  function getOcrLanguages() {
    return settings.value?.ocr_languages || {}
  }

  function getMaxFileSize() {
    return (settings.value?.max_file_size_mb || 25) * 1024 * 1024
  }

  function isFeatureEnabled(feature) {
    return settings.value?.features?.[feature] ?? true
  }

  return {
    settings,
    loading,
    error,
    load,
    getSupportedDoctypes,
    getOcrLanguages,
    getMaxFileSize,
    isFeatureEnabled,
  }
}
