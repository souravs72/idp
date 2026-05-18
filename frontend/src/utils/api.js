// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * API client for IDP backend endpoints.
 *
 * All functions call Frappe whitelisted methods via frappe-ui's
 * frappeRequest with CSRF token handling.
 */

import { frappeRequest } from 'frappe-ui'

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export function fetchSettings() {
  return frappeRequest({
    url: '/api/method/idp.api.settings.get_settings',
  })
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

export function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file, file.name)

  return fetch('/api/method/idp.api.upload.upload_document', {
    method: 'POST',
    headers: {
      'X-Frappe-CSRF-Token': window.csrf_token,
      Accept: 'application/json',
    },
    body: formData,
  }).then((res) => res.json())
}

// ---------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------

export function extractDocument({ fileUrl, targetDoctype, company, language }) {
  return frappeRequest({
    url: '/api/method/idp.api.extract.extract_document',
    params: {
      file_url: fileUrl,
      target_doctype: targetDoctype,
      company: company || undefined,
      language: language || 'en',
    },
  })
}

// ---------------------------------------------------------------------------
// Record creation
// ---------------------------------------------------------------------------

export function createDocument({
  targetDoctype,
  extractedData,
  company,
  createMissingMasters,
  itemDefaults,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.create.create_erp_document',
    params: {
      target_doctype: targetDoctype,
      extracted_data: JSON.stringify(extractedData),
      company: company || undefined,
      create_missing_masters: createMissingMasters ? 1 : 0,
      item_defaults: itemDefaults ? JSON.stringify(itemDefaults) : undefined,
    },
  })
}

export function getMissingMasters({ targetDoctype, extractedData, company }) {
  return frappeRequest({
    url: '/api/method/idp.api.create.get_missing_masters',
    params: {
      target_doctype: targetDoctype,
      extracted_data: JSON.stringify(extractedData),
      company: company || undefined,
    },
  })
}

// ---------------------------------------------------------------------------
// Comparison
// ---------------------------------------------------------------------------

export function compareDocument({
  fileUrl,
  compareDoctype,
  compareDocname,
  company,
  language,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.compare.compare_document',
    params: {
      file_url: fileUrl,
      compare_doctype: compareDoctype,
      compare_docname: compareDocname,
      company: company || undefined,
      language: language || 'en',
    },
  })
}

export function findMatchingRecord({
  fileUrl,
  targetDoctype,
  company,
  language,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.compare.find_matching_record',
    params: {
      file_url: fileUrl,
      target_doctype: targetDoctype,
      company: company || undefined,
      language: language || 'en',
    },
  })
}

// ---------------------------------------------------------------------------
// Bank statement (Phase 12)
// ---------------------------------------------------------------------------

export function extractBankStatement({ fileUrl, language }) {
  return frappeRequest({
    url: '/api/method/idp.api.extract.extract_bank_statement_api',
    params: {
      file_url: fileUrl,
      language: language || 'en',
    },
  })
}

export function reconcileBankStatement({
  bankAccount,
  transactions,
  company,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.extract.reconcile_bank_statement_api',
    method: 'POST',
    params: {
      bank_account: bankAccount,
      transactions: JSON.stringify(transactions || []),
      company: company || undefined,
    },
  })
}

// ---------------------------------------------------------------------------
// Conversation / Chatbot (Phase 17+)
// ---------------------------------------------------------------------------

export function createConversation({
  title,
  targetDoctype,
  company,
  llmProvider,
  llmModel,
  ocrLanguage,
  outputLanguage,
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.create_conversation',
    method: 'POST',
    params: {
      title: title || undefined,
      target_doctype: targetDoctype || undefined,
      company: company || undefined,
      llm_provider: llmProvider || undefined,
      llm_model: llmModel || undefined,
      ocr_language: ocrLanguage || undefined,
      output_language: outputLanguage || undefined,
    },
  })
}

export function listConversations({ status = 'Active', limit = 50 } = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.list_conversations',
    params: {
      status: status || undefined,
      limit: limit || 50,
    },
  })
}

export function getConversation(conversationId) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.get_conversation',
    params: { conversation_id: conversationId },
  })
}

export function postMessage({
  conversationId,
  content = '',
  attachments = [],
  role = 'user',
}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.post_message',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      content,
      attachments: JSON.stringify(attachments || []),
      role,
    },
  })
}

export function runAgent({
  conversationId,
  content = '',
  attachments = [],
  userConfirmedAction = null,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.run_agent',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      content,
      attachments: JSON.stringify(attachments || []),
      user_confirmed_action: userConfirmedAction
        ? JSON.stringify(userConfirmedAction)
        : undefined,
    },
  })
}

export function confirmCard({
  conversationId,
  messageId,
  action,
  editedPayload = null,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.confirm_card',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
      action,
      edited_payload: editedPayload
        ? JSON.stringify(editedPayload)
        : undefined,
    },
  })
}

export function getCardItemsPage({
  conversationId,
  messageId,
  page = 1,
  pageSize = 10,
}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.get_card_items_page',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
      page,
      page_size: pageSize,
    },
  })
}

export function archiveConversation(conversationId) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.archive_conversation',
    method: 'POST',
    params: { conversation_id: conversationId },
  })
}

// Phase 30 — request cancellation of the currently-running agent turn.
// The server flips an in-process cancellation flag; the agent loop polls
// it between iterations and persists a partial assistant message with
// ``status = "cancelled"``.
export function cancelTurn(conversationId) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.cancel_turn',
    method: 'POST',
    params: { conversation_id: conversationId },
  })
}

export function listAgentTools() {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.list_agent_tools',
  })
}

export function getChatDefaults() {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.get_chat_defaults',
  })
}

export function listLLMProviders() {
  return frappeRequest({
    url: '/api/method/idp.api.llm.list_providers',
  })
}

// ---------------------------------------------------------------------------
// Phase 24 — Item / Account search for the mapping table dropdowns
// ---------------------------------------------------------------------------

export function searchItems({ query, topN = 10 } = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.search_items',
    params: {
      query: query || '',
      top_n: topN,
    },
  })
}

export function searchAccounts({ query, company, topN = 10 } = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.search_accounts',
    params: {
      query: query || '',
      company: company || undefined,
      top_n: topN,
    },
  })
}

// ---------------------------------------------------------------------------
// Phase 25 — Mass-edit / bulk-match helpers for large item sets
// ---------------------------------------------------------------------------

export function bulkMatchItems({
  conversationId,
  messageId,
  matchThreshold = 0.6,
  onlyUnmatched = true,
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.bulk_match_items',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
      match_threshold: matchThreshold,
      only_unmatched: onlyUnmatched ? 1 : 0,
    },
  })
}

export function bulkAcceptSuggestions({ conversationId, messageId } = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.bulk_accept_suggestions',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
    },
  })
}

export function applyToAllRows({
  conversationId,
  messageId,
  fieldname,
  value,
  rowKind = 'items',
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.apply_to_all_rows',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
      fieldname,
      value: value == null ? '' : value,
      row_kind: rowKind,
    },
  })
}

// ---------------------------------------------------------------------------
// Phase 31 — Conversation UX Polish
// ---------------------------------------------------------------------------

export function estimateTurn({
  conversationId,
  content = '',
  attachments = [],
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.estimate_turn',
    method: 'POST',
    params: {
      conversation_id: conversationId || undefined,
      content,
      attachments: JSON.stringify(attachments || []),
    },
  })
}

export function suggestedPrompts() {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.suggested_prompts',
  })
}

export function searchConversations({
  query = '',
  status = null,
  targetDoctype = null,
  hasAttachments = false,
  dateRange = null,
  limit = 50,
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.search_conversations',
    params: {
      query: query || '',
      status: status || undefined,
      target_doctype: targetDoctype || undefined,
      has_attachments: hasAttachments ? 1 : 0,
      date_range: dateRange || undefined,
      limit: limit || 50,
    },
  })
}

export function deleteConversation(conversationId) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.delete_conversation',
    method: 'POST',
    params: { conversation_id: conversationId },
  })
}

export function reExtractField({
  conversationId,
  messageId,
  fieldName,
} = {}) {
  return frappeRequest({
    url: '/api/method/idp.api.conversation.re_extract_field',
    method: 'POST',
    params: {
      conversation_id: conversationId,
      message_id: messageId,
      field_name: fieldName,
    },
  })
}
