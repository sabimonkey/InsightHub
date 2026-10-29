import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LibraryPage } from './LibraryPage'

function json(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body })
}

describe('LibraryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows knowledge library cards without e2e labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/library')) {
          return json({
            items: [
              {
                source_id: 'src-1',
                display_name: 'shared note',
                title: '研究笔记标题',
                categories: ['knowledge'],
                analysis_status: '已完成',
                analysis_status_code: 'SUCCEEDED',
                summary_snippet: '摘要片段',
                last_collected_at: '2026-01-01T00:00:00Z',
              },
            ],
          })
        }
        throw new Error(`unexpected ${url}`)
      }),
    )
    render(<LibraryPage />)
    expect(await screen.findByText('知识库')).toBeTruthy()
    expect(await screen.findAllByText('研究笔记标题')).not.toHaveLength(0)
    expect(screen.getByTestId('knowledge-grid')).toBeTruthy()
    expect(screen.getByRole('button', { name: /资料卡片：研究笔记标题/ })).toBeTruthy()
  })
})
