// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

import { marked } from 'marked'

export function renderMarkdown(input) {
  if (input === null || input === undefined) return ''
  return marked.parse(String(input), { gfm: true, breaks: true, async: false })
}
