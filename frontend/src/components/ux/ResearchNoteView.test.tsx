import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ResearchNote } from '../../types'
import { ResearchNoteView } from './ResearchNoteView'

vi.mock('../../api', () => ({
  fetchResearchNote: vi.fn(),
  startAnalysisRun: vi.fn(),
  waitForAnalysis: vi.fn(),
}))

const baseNote: ResearchNote = {
  source_id: 'src-1',
  title: 'OpenKB 笔记',
  source_type: 'URL',
  source_type_label: '网页',
  author: '陈发财',
  original_url: 'https://example.com/post',
  canonical_url: null,
  collected_at: '2026-10-13T08:00:00Z',
  analysis_status: '已完成',
  analysis_status_code: 'SUCCEEDED',
  analysis_latest_status_code: 'SUCCEEDED',
  export_enabled: true,
  summary: null,
  highlights: [],
  claim_groups: {},
  categories: [],
  topics: [],
  reading: {
    core_summary: { paragraphs: ['这篇帖子主要介绍 OpenKB。'] },
    core_points: ['OpenKB 将资料组织成 Wiki。'],
    inferences_and_open: null,
    source_and_evidence: {
      source_type_label: '网页',
      author: '陈发财',
      collected_at: '2026-10-13T08:00:00Z',
      original_url: 'https://example.com/post',
      evidence_summary: { verified_count: 2, items: [] },
    },
  },
}

describe('ResearchNoteView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  it('shows reading sections and hides provider in body', async () => {
    const { fetchResearchNote } = await import('../../api')
    vi.mocked(fetchResearchNote).mockResolvedValue(baseNote)
    render(<ResearchNoteView sourceId="src-1" open onClose={() => undefined} />)
    expect(await screen.findByText('核心摘要')).toBeInTheDocument()
    expect(screen.getByText('核心要点')).toBeInTheDocument()
    expect(screen.getByText('来源与依据')).toBeInTheDocument()
    expect(screen.queryByText(/Provider/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制 Markdown' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重新分析' })).toBeInTheDocument()
  })

  it('shows evidence validation details for a readable partial result', async () => {
    const { fetchResearchNote } = await import('../../api')
    vi.mocked(fetchResearchNote).mockResolvedValue({
      ...baseNote,
      analysis_status: '部分完成',
      analysis_status_code: 'PARTIAL',
      partial_summary: '已保留可验证内容。',
      partial_issues: ['quote not in chunk'],
    })
    render(<ResearchNoteView sourceId="src-1" open onClose={() => undefined} />)
    expect(await screen.findByText('部分完成')).toBeInTheDocument()
    expect(screen.getByText('已保留可验证内容。')).toBeInTheDocument()
    expect(screen.getByText('查看证据校验明细（1）')).toBeInTheDocument()
    fireEvent.click(screen.getByText('查看证据校验明细（1）'))
    expect(await screen.findByText('quote not in chunk')).toBeInTheDocument()
  })

  it('shows pending state and disables export', async () => {
    const { fetchResearchNote } = await import('../../api')
    vi.mocked(fetchResearchNote).mockResolvedValue({
      source_id: 'src-pending',
      title: '等待中资料',
      source_type: 'TEXT',
      original_url: null,
      canonical_url: null,
      collected_at: null,
      analysis_status: '等待中',
      analysis_status_code: 'PENDING',
      analysis_latest_status_code: 'PENDING',
      export_enabled: false,
      summary: null,
      highlights: [],
      claim_groups: {},
      categories: [],
      topics: [],
      reading: null,
      analysis_progress: {
        run_id: 'run-p',
        status: 'PENDING',
        stage: 'QUEUED',
        stage_label: '已提交，等待后台任务',
      },
    })
    render(<ResearchNoteView sourceId="src-pending" open onClose={() => undefined} />)
    expect(await screen.findByText('正在生成学习笔记')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '复制 Markdown' })).not.toBeInTheDocument()
  })

  it('ignores stale note payload for a different source', async () => {
    const { fetchResearchNote } = await import('../../api')
    vi.mocked(fetchResearchNote).mockImplementation(async (id: string) => {
      if (id === 'src-a') {
        await new Promise((resolve) => setTimeout(resolve, 30))
        return { ...baseNote, source_id: 'src-a', title: 'Note A' }
      }
      return { ...baseNote, source_id: 'src-b', title: 'Note B' }
    })
    const { rerender } = render(<ResearchNoteView sourceId="src-a" open onClose={() => undefined} />)
    rerender(<ResearchNoteView sourceId="src-b" open onClose={() => undefined} />)
    expect(await screen.findByText('Note B')).toBeInTheDocument()
    expect(screen.queryByText('Note A')).not.toBeInTheDocument()
  })

  it('shows failed state with collapsed details', async () => {
    const { fetchResearchNote } = await import('../../api')
    vi.mocked(fetchResearchNote).mockResolvedValue({
      ...baseNote,
      analysis_status: '分析失败',
      analysis_status_code: 'FAILED',
      analysis_latest_status_code: 'FAILED',
      export_enabled: false,
      reading: null,
      analysis_failure: {
        error_code: 'STRUCTURED_OUTPUT_INVALID',
        error_message: 'bad json',
        user_message: '模型输出未能通过结构化校验，请重试或更换模型。',
        run_id: 'run-1',
        supersedes_content: false,
      },
    })
    render(<ResearchNoteView sourceId="src-1" open onClose={() => undefined} />)
    expect(await screen.findByText('AI 分析失败')).toBeInTheDocument()
    expect(screen.getByText('查看详情')).toBeInTheDocument()
  })
})
