// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Minimal, dependency-free Markdown renderer for assistant chat
 * messages.  Supports just enough syntax to make LLM output readable
 * without pulling in a 30 KB markdown parser:
 *
 *   - fenced code blocks (```lang\n...\n```)
 *   - inline code: `code`
 *   - bold: **text**
 *   - italic: *text* / _text_
 *   - links: [label](https://...)
 *   - bullet lists: lines starting with "- " or "* "
 *   - line breaks
 *
 * The output is HTML-escaped first, so user/LLM content cannot inject
 * tags.  The result is meant to be rendered with v-html.
 */

const HTML_ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => HTML_ESCAPES[c])
}

function renderInline(text) {
  // text is already HTML-escaped
  let out = text
  // inline code first so other replacements don't touch its content
  out = out.replace(/`([^`]+)`/g, (_, code) => {
    return `<code class="rounded bg-gray-100 px-1 py-0.5 font-mono text-[0.85em] dark:bg-gray-800">${code}</code>`
  })
  // links — only http(s) and mailto
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g,
    (_, label, href) =>
      `<a href="${href}" target="_blank" rel="noopener noreferrer" class="text-blue-700 underline dark:text-blue-300">${label}</a>`,
  )
  // bold
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // italic
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  out = out.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>')
  return out
}

export function renderMarkdown(input) {
  if (input === null || input === undefined) return ''
  const escaped = escapeHtml(String(input))

  // Pull out fenced code blocks first.
  const blocks = []
  const fencePattern = /```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g
  const withPlaceholders = escaped.replace(fencePattern, (_, lang, code) => {
    const idx = blocks.length
    blocks.push({ lang, code })
    return `\u0000BLOCK${idx}\u0000`
  })

  const lines = withPlaceholders.split('\n')
  const html = []
  let inList = false

  function flushList() {
    if (inList) {
      html.push('</ul>')
      inList = false
    }
  }

  for (const raw of lines) {
    const line = raw
    if (/^\s*[-*]\s+/.test(line)) {
      if (!inList) {
        html.push('<ul class="list-disc list-inside space-y-0.5">')
        inList = true
      }
      const item = line.replace(/^\s*[-*]\s+/, '')
      html.push(`<li>${renderInline(item)}</li>`)
      continue
    }
    flushList()

    if (line.trim() === '') {
      html.push('')
      continue
    }
    html.push(renderInline(line))
  }
  flushList()

  let body = html.join('\n')

  // Restore code blocks
  body = body.replace(/\u0000BLOCK(\d+)\u0000/g, (_, raw) => {
    const block = blocks[Number(raw)] || { code: '' }
    const langLabel = block.lang
      ? `<span class="text-[10px] uppercase tracking-wide text-gray-500">${block.lang}</span>`
      : ''
    return `<div class="my-2"><div class="flex justify-between items-center px-2 pt-1">${langLabel}</div><pre class="overflow-x-auto rounded bg-gray-900 p-3 text-xs text-gray-100"><code>${block.code}</code></pre></div>`
  })

  // Treat blank lines as paragraph separators.
  body = body
    .split(/\n{2,}/)
    .map((chunk) => {
      const trimmed = chunk.trim()
      if (!trimmed) return ''
      if (/^<(ul|pre|div|ol|h\d|blockquote)/.test(trimmed)) return trimmed
      return `<p>${trimmed.replace(/\n/g, '<br />')}</p>`
    })
    .join('\n')

  return body
}
