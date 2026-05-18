// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Phase 31 — Cost footer + pre-flight cost warning.
 *
 * Exposes:
 *   - estimate({ content, attachments }): wraps idp.api.conversation.estimate_turn
 *   - confirmIfNeeded({ content, attachments }): when the estimated turn
 *     would push the user past their daily budget, opens a window.confirm
 *     dialog and returns whether the user wants to continue.  Cancelling
 *     the dialog returns ``false`` and no token is consumed.
 *
 * Settings gate: ``IDP Settings.enable_preflight_warning`` controls the
 * dialog.  When off, ``confirmIfNeeded`` resolves to ``true`` immediately.
 */

import { ref } from 'vue'
import { estimateTurn } from '@/utils/api'
import { useSettings } from '@/composables/useSettings'

export function useCost() {
  const lastEstimate = ref(null)
  const checking = ref(false)
  const { settings } = useSettings()

  async function estimate({ conversationId, content = '', attachments = [] } = {}) {
    checking.value = true
    try {
      const out = await estimateTurn({ conversationId, content, attachments })
      lastEstimate.value = out
      return out
    } finally {
      checking.value = false
    }
  }

  function isPreflightEnabled() {
    const v = settings.value?.enable_preflight_warning
    // Default to ON when settings haven't loaded yet — matches Frappe
    // default for the new field.
    if (v == null) return true
    return !!Number(v)
  }

  /**
   * Run the estimator and, when the estimate would exceed the daily
   * budget, open a confirmation dialog.  Returns ``true`` when the
   * caller may proceed with sending the turn.
   */
  async function confirmIfNeeded({ conversationId, content = '', attachments = [] } = {}) {
    if (!isPreflightEnabled()) return true
    let est
    try {
      est = await estimate({ conversationId, content, attachments })
    } catch (err) {
      // Estimator failure should never block the actual send — log
      // and proceed.
      // eslint-disable-next-line no-console
      console.warn('[useCost] estimate failed; skipping pre-flight', err)
      return true
    }
    if (!est?.would_exceed) return true

    const tokens = est.estimated_tokens || 0
    const cap = est.daily_cap || 0
    const used = est.daily_used || 0
    const usd = Number(est.estimated_cost_usd || 0).toFixed(4)
    const msg =
      `Heads up — this turn could use about ${tokens} tokens ($${usd}).\n\n` +
      `You've used ${used} of ${cap} tokens today.\n\n` +
      `Continue anyway?`
    return window.confirm(msg)
  }

  return {
    lastEstimate,
    checking,
    estimate,
    confirmIfNeeded,
    isPreflightEnabled,
  }
}
