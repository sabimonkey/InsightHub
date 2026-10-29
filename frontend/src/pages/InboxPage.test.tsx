import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InboxPage } from './InboxPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('InboxPage', () => {
  it('renders centered add panel and recent sources', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/inbox')) {
          expect(url).toContain('page_size=5')
          return jsonResponse({
            items: [
              {
                ingestion_id: 'ing-1',
                source_id: 'src-1',
                display_name: 'https://example.com/post',
                title: 'Example Post',
                source_type: 'URL',
                collected_at: '2026-09-25T02:00:00Z',
                status: 'STORED',
                duplicate_detected: false,
                analysis_status: '已完成',
                analysis_status_code: 'SUCCEEDED',
                extraction_status_label: '正文已提取',
                has_usable_content: true,
              },
            ],
            page: 1,
            page_size: 5,
            total: 1,
          })
        }
        throw new Error(`unexpected ${url}`)
      }),
    )

    render(<InboxPage />)
    expect(await screen.findByTestId('add-source-panel')).toBeInTheDocument()
    expect(screen.getByText('最近收集')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /最近资料：Example Post/ })).toBeInTheDocument()
    expect(screen.queryByTestId('collection-split-left')).toBeNull()
  })

  it('shows duplicate collection feedback after adding text', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/inbox')) {
        return jsonResponse({ items: [], page: 1, page_size: 5, total: 0 })
      }
      if (url.includes('/api/ingest/text') && init?.method === 'POST') {
        return jsonResponse({
          source: { id: 'src-1', source_type: 'TEXT', display_name: 'same note', status: 'STORED' },
          ingestion: { id: 'ing-dup', duplicate_detected: true, status: 'STORED' },
          asset: null,
          duplicate_detected: true,
          duplicate_reason: 'content_hash',
          message: 'duplicate',
        })
      }
      throw new Error(`unexpected ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)
    await userEvent.click(screen.getByRole('tab', { name: '文本' }))
    await userEvent.type(screen.getByRole('textbox', { name: '文本' }), 'same note body')
    await userEvent.click(screen.getByRole('button', { name: '添加资料' }))
    expect(await screen.findByText('已识别重复资料')).toBeInTheDocument()
  })

  it('navigates to library when clicking recent row', async () => {
    const openLibrary = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes('/api/inbox')) {
          return jsonResponse({
            items: [
              {
                ingestion_id: 'ing-2',
                source_id: 'src-2',
                display_name: 'Row',
                title: 'Row Title',
                collected_at: '2026-09-25T02:00:00Z',
                status: 'STORED',
                duplicate_detected: false,
              },
            ],
            page: 1,
            page_size: 5,
            total: 1,
          })
        }
        throw new Error('unexpected')
      }),
    )
    render(<InboxPage onOpenLibrary={openLibrary} />)
    await userEvent.click(await screen.findByRole('button', { name: /最近资料：Row Title/ }))
    expect(openLibrary).toHaveBeenCalledWith('src-2')
  })
})
