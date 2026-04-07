// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Formatting utilities for the IDP frontend.
 *
 * Number, date, and currency formatters that respect the user's
 * locale and ERPNext conventions.
 */

/**
 * Format a number with locale-aware grouping.
 * @param {number|string} value
 * @param {number} decimals - decimal places (default 2)
 * @returns {string}
 */
export function formatNumber(value, decimals = 2) {
  const num = parseFloat(value)
  if (isNaN(num)) return value ?? ''
  return num.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/**
 * Format a currency value.
 * @param {number|string} value
 * @param {string} currency - ISO currency code (default 'INR')
 * @returns {string}
 */
export function formatCurrency(value, currency = 'INR') {
  const num = parseFloat(value)
  if (isNaN(num)) return value ?? ''
  try {
    return num.toLocaleString(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  } catch {
    // Fallback if currency code is invalid
    return `${currency} ${formatNumber(num, 2)}`
  }
}

/**
 * Format a date string to a human-readable format.
 * @param {string} dateStr - ISO date string (YYYY-MM-DD)
 * @returns {string}
 */
export function formatDate(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return dateStr
  }
}

/**
 * Format a timestamp to relative time ("2 min ago", "1 hour ago").
 * @param {string} timestamp - ISO timestamp
 * @returns {string}
 */
export function timeAgo(timestamp) {
  if (!timestamp) return ''
  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const seconds = Math.floor((now - then) / 1000)

  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hour(s) ago`
  return `${Math.floor(seconds / 86400)} day(s) ago`
}

/**
 * Format file size in human-readable units.
 * @param {number} bytes
 * @returns {string}
 */
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/**
 * Format a confidence score as a percentage.
 * @param {number} score - float 0.0-1.0
 * @returns {string}
 */
export function formatConfidence(score) {
  if (score == null) return 'N/A'
  return `${(score * 100).toFixed(1)}%`
}
