import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Modal } from 'antd'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BriefPage } from './BriefPage'

afterEach(() => {
  cleanup()
  Modal.destroyAll()
  document.querySelectorAll('.ant-modal-root').forEach((node) => node.remove())
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function note(id: string, title: string, completedAt: string) {
  return {
    id,
    title,
    status: 'SUCCEEDED',
    start_date: '2026-10-01',
    end_date: '2026-10-28',
    completed_at: completedAt,
    content_markdown: `# ${title}`,
    learning_note: { title, highlights: [], theme_notes: [], sections: {}, follow_ups: [] },
    included_source_count: 1,
    selected_source_count: 1,
    excluded_source_count: 0,
    exclusion_reasons: {},
    error_code: null,
    error_message: null,
    filters: { category_slugs: [] },
    citations: [],
    source_index: [],
  }
}

function findClearDialog() {
  return screen.getAllByRole('dialog').find((dialog) => dialog.textContent?.includes('将删除所有学习笔记历史及其正文')) as HTMLElement
}

describe('BriefPage history actions', () => {
  it('deletes one note, confirms clearing remaining history, and reflects persisted list state', async () => {
    const user = userEvent.setup()
    let rows = [note('newest', '最新笔记', '2026-10-28T10:00:00Z'), note('older', '较旧笔记', '2026-10-27T10:00:00Z')]
    const deleted: string[] = []
    let clearCalls = 0

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      if (url === '/api/categories' || url === '/api/topics') return jsonResponse([])
      if (url === '/api/briefs' && init?.method === 'DELETE') {
        clearCalls += 1
        rows = []
        return jsonResponse({ deleted_count: 1 })
      }
      if (url.endsWith('/api/briefs/newest') && init?.method === 'DELETE') {
        deleted.push('newest')
        rows = rows.filter((item) => item.id !== 'newest')
        return jsonResponse({ deleted: true, id: 'newest' })
      }
      if (url === '/api/briefs' && !init?.method) return jsonResponse({ briefs: rows })
      if (url.includes('/api/briefs/')) {
        const id = url.split('/').pop() ?? ''
        return jsonResponse(rows.find((item) => item.id === id) ?? { brief: null })
      }
      return jsonResponse({})
    }))

    render(<BriefPage />)
    const history = await screen.findByText('学习笔记历史')
    const historyRegion = history.parentElement?.parentElement
    expect(historyRegion).not.toBeNull()
    await waitFor(() => expect(within(historyRegion as HTMLElement).getByText('最新笔记')).toBeTruthy())
    const noteRows = within(historyRegion as HTMLElement).getAllByRole('button', { name: /^history / })
    expect(noteRows[0].getAttribute('aria-label')).toBe('history newest')

    await user.click(within(historyRegion as HTMLElement).getByRole('button', { name: '删除学习笔记 最新笔记' }))
    await user.click(await screen.findByRole('button', { name: '删除笔记' }))
    await waitFor(() => expect(deleted).toEqual(['newest']))
    expect(await within(historyRegion as HTMLElement).findByText('较旧笔记')).toBeTruthy()
    await user.click(within(historyRegion as HTMLElement).getByRole('button', { name: '清空历史' }))
    await waitFor(() => expect(findClearDialog()).toBeTruthy())
    const clearDialog = findClearDialog()
    expect(clearDialog).not.toBeNull()
    await user.click(within(clearDialog).getByRole('button', { name: '清空历史' }))
    await waitFor(() => expect(clearCalls).toBe(1))
    expect(await within(historyRegion as HTMLElement).findByText('暂无学习笔记历史')).toBeTruthy()
  })

  it('canceling the confirmation does not send a clear request', async () => {
    const user = userEvent.setup()
    const row = note('cancel-kept', '保留笔记', '2026-10-28T10:00:00Z')
    let clearCalls = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      if (url === '/api/categories' || url === '/api/topics') return jsonResponse([])
      if (url === '/api/briefs' && init?.method === 'DELETE') {
        clearCalls += 1
        return jsonResponse({ deleted_count: 1 })
      }
      if (url === '/api/briefs') return jsonResponse({ briefs: [row] })
      return jsonResponse(row)
    }))

    render(<BriefPage />)
    const history = await screen.findByText('学习笔记历史')
    const region = history.parentElement?.parentElement as HTMLElement
    await user.click(within(region).getByRole('button', { name: '清空历史' }))
    await waitFor(() => expect(findClearDialog()).toBeTruthy())
    fireEvent.click(within(findClearDialog()).getByRole('button', { name: /取\s*消/ }))

    expect(clearCalls).toBe(0)
    expect(within(region).getByText('保留笔记')).toBeTruthy()
  })

  it('surfaces the server method error and keeps history when clearing fails', async () => {
    const user = userEvent.setup()
    const row = note('kept', '保留笔记', '2026-10-28T10:00:00Z')
    const clearRequest = vi.fn(async () => jsonResponse({ detail: 'Method Not Allowed' }, 405))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      if (url === '/api/categories' || url === '/api/topics') return jsonResponse([])
      if (url === '/api/briefs' && init?.method === 'DELETE') return clearRequest()
      if (url === '/api/briefs') return jsonResponse({ briefs: [row] })
      return jsonResponse(row)
    }))

    render(<BriefPage />)
    const history = await screen.findByText('学习笔记历史')
    const region = history.parentElement?.parentElement as HTMLElement
    await user.click(within(region).getByRole('button', { name: '清空历史' }))
    await waitFor(() => expect(findClearDialog()).toBeTruthy())
    const dialog = findClearDialog()
    fireEvent.click(within(dialog).getByRole('button', { name: /清空历史/ }))

    expect(await screen.findByText('清空失败（HTTP 405）：Method Not Allowed')).toBeTruthy()
    expect(await within(region).findByText('保留笔记')).toBeTruthy()
    expect(clearRequest).toHaveBeenCalledTimes(1)
  })

  it('renders four configuration sections inside one outer card and separates results', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      if (url === '/api/categories' || url === '/api/topics') return jsonResponse([])
      if (url === '/api/briefs') return jsonResponse({ briefs: [] })
      return jsonResponse({})
    }))

    const { container } = render(<BriefPage />)
    await screen.findByText('新建学习笔记')
    const card = container.querySelector('.brief-config-card')
    expect(card).not.toBeNull()
    for (const section of ['时间范围', '资料范围', '主题与生成设置', '资料预览']) {
      expect(card?.querySelector(`[aria-label="${section}"]`)).not.toBeNull()
    }
    expect(card?.querySelectorAll('.ant-card')).toHaveLength(0)
    expect(container.querySelector('.brief-result-area')).not.toBeNull()
  })

  it('restores a persisted failed generation instead of showing a stale loading state', async () => {
    const failed = {
      ...note('failed-task', '失败任务', '2026-10-28T11:00:00Z'),
      status: 'FAILED',
      content_markdown: '模型没有返回可校验的 JSON。',
      error_code: 'STRUCTURED_OUTPUT_INVALID',
      error_message: '模型没有返回可校验的 JSON。',
      learning_note: null,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      if (url === '/api/categories' || url === '/api/topics') return jsonResponse([])
      if (url === '/api/briefs') return jsonResponse({ briefs: [failed] })
      return jsonResponse(failed)
    }))

    render(<BriefPage />)

    expect(await screen.findByText('模型没有返回可校验的 JSON。')).toBeTruthy()
    expect(screen.queryByText('正在生成学习笔记…')).toBeNull()
  })
})
