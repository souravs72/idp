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
