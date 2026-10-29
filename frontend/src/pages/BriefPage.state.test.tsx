import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BriefPage } from './BriefPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const septNote = {
  title: '九月笔记',
  highlights: ['九月重点。'],
  theme_notes: [],
  sections: {},
  follow_ups: [],
}

const octNote = {
  title: '十月笔记',
  highlights: ['十月重点。'],
  theme_notes: [],
  sections: {},
  follow_ups: [],
}

describe('BriefPage state isolation', () => {
  it('keeps history reading while draft uses new month for preview and create', { timeout: 20_000 }, async () => {
    const user = userEvent.setup()
    let previewBody: { start_date?: string } | null = null
    let createBody: { start_date?: string; end_date?: string; brief_id?: string } | null = null
    const septId = 'brief-sept'
    const octId = 'brief-oct'

    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/llm/providers')) return jsonResponse([{ configured: true }])
        if (url.includes('/api/categories')) return jsonResponse([])
        if (url.includes('/api/topics')) return jsonResponse([])
        if (url.includes('/api/briefs/preview') && init?.method === 'POST') {
          previewBody = JSON.parse(String(init.body)) as { start_date?: string }
          return jsonResponse({
            sources: [],
            stats: { total_in_range: 34, included_for_brief: 26, exclusion_reasons: {} },
            diagnosis: { code: 'OK', message: 'preview ok' },
          })
        }
        if (url.endsWith('/api/briefs') && init?.method === 'POST') {
          createBody = JSON.parse(String(init.body)) as { start_date?: string; end_date?: string }
          return jsonResponse({
            id: octId,
            status: 'SUCCEEDED',
            start_date: createBody.start_date,
            end_date: createBody.end_date,
            included_source_count: 26,
            selected_source_count: 34,
            excluded_source_count: 8,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            filters: {},
            citations: [],
            source_index: [],
            content_markdown: 'oct',
            learning_note: octNote,
          })
        }
        if (url.includes(`/api/briefs/${septId}`)) {
          return jsonResponse({
            id: septId,
            status: 'SUCCEEDED',
            start_date: '2026-09-01',
            end_date: '2026-09-30',
            included_source_count: 0,
            selected_source_count: 0,
            excluded_source_count: 0,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            filters: {},
            citations: [],
            source_index: [],
            content_markdown: '',
            learning_note: septNote,
          })
        }
        if (url.includes(`/api/briefs/${octId}`)) {
          return jsonResponse({
            id: octId,
            status: 'SUCCEEDED',
            start_date: '2026-10-01',
            end_date: '2026-10-22',
            included_source_count: 26,
            selected_source_count: 34,
            excluded_source_count: 8,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            filters: {},
            citations: [],
            source_index: [],
            content_markdown: 'oct',
            learning_note: octNote,
          })
        }
        if (url.endsWith('/api/briefs')) {
          return jsonResponse({
            briefs: [
              {
                id: septId,
                status: 'SUCCEEDED',
                start_date: '2026-09-01',
                end_date: '2026-09-30',
                included_source_count: 0,
                selected_source_count: 0,
                excluded_source_count: 0,
                exclusion_reasons: {},
                error_code: null,
                error_message: null,
                filters: {},
                citations: [],
                source_index: [],
                content_markdown: '',
                learning_note: septNote,
              },
            ],
          })
        }
        return jsonResponse({})
      }),
    )

    render(<BriefPage />)
    await user.click(await screen.findByRole('button', { name: `history ${septId}` }))
    expect(await screen.findByText('九月重点。')).toBeTruthy()
    expect(screen.getByLabelText('reading context history')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'preset this month' }))
    expect((screen.getByLabelText('brief start') as HTMLInputElement).value).toMatch(/^2026-10-01$/)

    await user.click(screen.getByRole('button', { name: '预览资料' }))
    await waitFor(() => expect(previewBody?.start_date).toMatch(/^2026-10-/))
    expect(screen.getByText('九月重点。')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: '生成学习笔记' }))
    await waitFor(() => expect(createBody?.start_date).toMatch(/^2026-10-/))
    expect(createBody?.start_date).not.toBe('2026-09-01')
    expect(await screen.findByText('十月重点。')).toBeTruthy()
    expect(screen.getByLabelText('reading context generation')).toBeTruthy()
  })
})
