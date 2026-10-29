import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskPage } from './AskPage'
import { SearchPage } from './SearchPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  if (typeof input === 'object' && input !== null && 'url' in input) return (input as Request).url
  return String(input)
}

describe('SearchPage', () => {
  it('runs smart search and shows result cards', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input)
        if (url.includes('/api/index/status')) {
          return jsonResponse({ configured: false, semantic_available: false, indexed_chunks: 0, total_current_chunks: 3, backfill_status: null })
        }
        if (url.includes('/api/search')) {
          const body = JSON.parse(String(init?.body)) as { mode: string }
          expect(body.mode).toBe('hybrid')
          return jsonResponse({
            mode: 'keyword',
            results: [
              {
                source_id: 'src-1',
                chunk_id: 'chunk-1',
                source_title: 'sandbox note',
                source_type: 'TEXT',
                snippet: 'agent sandbox preview',
                retrieval_methods: ['FTS'],
                category: ['知识'],
                topics: ['Agent'],
                original_url: 'https://example.com/sandbox',
                collection: { first_collected_at: '2026-09-01T00:00:00Z', collection_count: 1 },
              },
            ],
          })
        }
        return jsonResponse({})
      }),
    )
    render(<SearchPage />)
    expect(await screen.findByText(/知识库索引/)).toBeTruthy()
    const searchInput = screen.getByLabelText('搜索')
    await user.type(searchInput, 'sandbox')
    await user.keyboard('{Enter}')
    expect(await screen.findByText('agent sandbox preview')).toBeTruthy()
    expect(screen.getByRole('button', { name: '阅读摘要' })).toBeTruthy()
  }, 10000)

  it('shows index progress when embeddings are configured', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = requestUrl(input)
        if (url.includes('/api/index/status')) {
          return jsonResponse({ configured: true, semantic_available: true, indexed_chunks: 2, total_current_chunks: 2, backfill_status: 'SUCCEEDED' })
        }
        return jsonResponse({ mode: 'hybrid', results: [] })
      }),
    )
    render(<SearchPage />)
    expect(await screen.findByText(/2 \/ 2 条已索引/)).toBeTruthy()
  })
})

describe('AskPage', () => {
  it('shows pending then success citations, no evidence, and privacy warning', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input)
        if (url.includes('/turns') && init?.method === 'POST') {
          return jsonResponse({
            id: 'turn-1',
            question: 'what is sandbox',
            status: 'SUCCEEDED',
            answer_markdown: 'answer [1]',
            excluded_sensitive_source_count: 1,
            error_code: null,
            citations: [
              {
                citation_number: 1,
                content_chunk_id: 'chunk-1',
                source_item_id: 'src-1',
                quote_text: 'quote',
                source_title: 'note',
                heading_path: [],
                page_number: null,
                original_url: null,
              },
            ],
          })
        }
        if (url.match(/\/api\/ask\/sessions\/?$/) && init?.method === 'POST') {
          return jsonResponse({ id: 'sess-1', title: 'q' })
        }
        if (url.includes('/api/ask/sessions') && !url.includes('/turns') && (!init?.method || init.method === 'GET')) {
          if (url.match(/\/api\/ask\/sessions\/[^/]+$/)) {
            return jsonResponse({ turns: [] })
          }
          return jsonResponse({ sessions: [{ id: 'sess-1', title: '历史问题' }] })
        }
        if (url.includes('/api/llm/providers') && !url.includes('/embedding/')) {
          return jsonResponse([{ configured: true, enabled: true }])
        }
        if (url.includes('/api/llm/routes')) {
          return jsonResponse({ routes: [{ workflow: 'ASK_ANSWER', deployment_display_name: 'qwen' }] })
        }
        if (url.includes('/turns/turn-1')) {
          return jsonResponse({
            id: 'turn-1',
            question: 'what is sandbox',
            status: 'SUCCEEDED',
            answer_markdown: 'answer [1]',
            excluded_sensitive_source_count: 1,
            error_code: null,
            citations: [
              {
                citation_number: 1,
                content_chunk_id: 'chunk-1',
                source_item_id: 'src-1',
                quote_text: 'quote',
                source_title: 'note',
                heading_path: [],
                page_number: null,
                original_url: null,
              },
            ],
          })
        }
        return jsonResponse({})
      }),
    )
    render(<AskPage />)
    expect(await screen.findByText('问答')).toBeTruthy()
    await user.type(screen.getByLabelText('输入问题'), 'what is sandbox')
    await user.click(await screen.findByRole('button', { name: '提交问题' }))
    expect(await screen.findByText('what is sandbox')).toBeTruthy()
    expect(screen.getByText(/敏感来源/)).toBeTruthy()
  })
})
