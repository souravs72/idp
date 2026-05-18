// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Phase 31 G14 — suggested prompts for empty conversations.
 *
 * Wraps idp.api.conversation.suggested_prompts and caches the result
 * for the lifetime of the SPA session (the backend already caches per
 * user for ~30 min, so the second call is effectively free).
 *
 * Settings gate: ``IDP Settings.enable_suggested_prompts``.  When off
 * ``load()`` returns an empty list.
 */

import { ref } from 'vue'
import { suggestedPrompts as apiSuggested } from '@/utils/api'
import { useSettings } from '@/composables/useSettings'

const cache = ref(null)
const loading = ref(false)

export function useSuggestedPrompts() {
  const { settings } = useSettings()

  function isEnabled() {
    const v = settings.value?.enable_suggested_prompts
    if (v == null) return true
    return !!Number(v)
  }

  async function load({ force = false } = {}) {
    if (!isEnabled()) {
      cache.value = []
      return []
    }
    if (cache.value && !force) return cache.value
    loading.value = true
    try {
      const out = await apiSuggested()
      cache.value = Array.isArray(out) ? out : []
      return cache.value
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[useSuggestedPrompts] load failed', err)
      cache.value = []
      return []
    } finally {
      loading.value = false
    }
  }

  function invalidate() {
    cache.value = null
  }

  return {
    prompts: cache,
    loading,
    isEnabled,
    load,
    invalidate,
  }
}
