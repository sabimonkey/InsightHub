import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BriefPage } from './BriefPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const learningNote = {
  title: '学习摘要',
  highlights: ['沙箱结论。'],
  theme_notes: [],
  sections: { 关键事实: [{ text: '沙箱', label: '关键事实' }] },
  follow_ups: [],
}

describe('BriefPage', () => {
  it('previews sources, shows partial and no content, and lists citations', { timeout: 15_000 }, async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/api/llm/providers')) return jsonResponse([{ configured: true }])
        if (url.includes('/api/categories')) return jsonResponse([{ id: 'cat-1', name: '知识', slug: 'knowledge' }, { id: 'cat-2', name: '缺失', slug: 'missing' }])
        if (url.includes('/api/topics')) return jsonResponse([{ id: 'topic-1', name: 'Agent' }])
        if (url.includes('/api/briefs/old') && !url.includes('regenerate')) {
          return jsonResponse({
            id: 'old',
            title: '旧摘要',
            status: 'SUCCEEDED',
            start_date: '2026-09-01',
            end_date: '2026-09-01',
            filters: { category_slugs: ['knowledge'] },
            citations: [],
            source_index: [],
            content_markdown: '旧',
            included_source_count: 1,
            selected_source_count: 1,
            excluded_source_count: 0,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            learning_note: learningNote,
          })
        }
        if (url.includes('/regenerate')) {
          return jsonResponse({
            id: 'brief-2',
            title: '学习摘要',
            status: 'SUCCEEDED',
            start_date: '2026-09-25',
            end_date: '2026-09-25',
            content_markdown: '新版本。[1]',
            included_source_count: 2,
            selected_source_count: 3,
            excluded_source_count: 1,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            regenerated_from_id: 'brief-1',
            filters: { category_slugs: [] },
            citations: [],
            source_index: [],
            learning_note: learningNote,
          })
        }
        if (url.endsWith('/api/briefs') && init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { category_slugs: string[]; start_date: string }
          if (body.category_slugs.includes('missing')) {
            return jsonResponse({
              id: 'brief-empty',
              title: null,
              status: 'NO_CONTENT',
              start_date: body.start_date,
              end_date: body.start_date,
              content_markdown: '该范围内没有符合条件的资料。',
              included_source_count: 0,
              selected_source_count: 0,
              excluded_source_count: 0,
              exclusion_reasons: {},
              error_code: 'BRIEF_NO_SOURCES_IN_RANGE',
              error_message: '所选日期与分类范围内没有任何收藏资料。',
              filters: { category_slugs: body.category_slugs },
              citations: [],
              source_index: [],
              learning_note: null,
            })
          }
          return jsonResponse({
            id: 'brief-1',
            title: '学习摘要',
            status: 'SUCCEEDED',
            start_date: body.start_date,
            end_date: body.start_date,
            content_markdown: '沙箱结论。[1]',
            included_source_count: 2,
            selected_source_count: 3,
            excluded_source_count: 1,
            exclusion_reasons: { NO_ANALYSIS: 1 },
            error_code: 'PARTIAL_CONTENT',
            error_message: null,
            filters: { category_slugs: body.category_slugs },
            citations: [{ citation_number: 1, content_chunk_id: 'chunk-1', source_item_id: 'src-1', quote_text: '沙箱' }],
            source_index: [{ citation_number: 1, title: 'note', original_url: 'https://example.com/a', canonical_url: 'https://example.com/a', filename: null }],
            learning_note: learningNote,
          })
        }
        if (url.match(/\/api\/briefs\/[^/?]+$/) && (!init?.method || init.method === 'GET')) {
          const id = url.split('/').pop()!
          if (id === 'brief-1') {
            return jsonResponse({
              id: 'brief-1',
              title: '学习摘要',
              status: 'SUCCEEDED',
              start_date: '2026-09-25',
              end_date: '2026-09-25',
              content_markdown: '沙箱结论。[1]',
              included_source_count: 2,
              selected_source_count: 3,
              excluded_source_count: 1,
              exclusion_reasons: { NO_ANALYSIS: 1 },
              error_code: 'PARTIAL_CONTENT',
              error_message: null,
              filters: { category_slugs: [] },
              citations: [{ citation_number: 1, content_chunk_id: 'chunk-1', source_item_id: 'src-1', quote_text: '沙箱' }],
              source_index: [{ citation_number: 1, title: 'note', original_url: 'https://example.com/a', canonical_url: 'https://example.com/a', filename: null }],
              learning_note: learningNote,
            })
          }
          if (id === 'brief-empty') {
            return jsonResponse({
              id: 'brief-empty',
              title: null,
              status: 'NO_CONTENT',
              start_date: '2026-09-01',
              end_date: '2026-09-01',
              content_markdown: '该范围内没有符合条件的资料。',
              included_source_count: 0,
              selected_source_count: 0,
              excluded_source_count: 0,
              exclusion_reasons: {},
              error_code: 'BRIEF_NO_SOURCES_IN_RANGE',
              error_message: '所选日期与分类范围内没有任何收藏资料。',
              filters: { category_slugs: ['missing'] },
              citations: [],
              source_index: [],
              learning_note: null,
            })
          }
          if (id === 'brief-2') {
            return jsonResponse({
              id: 'brief-2',
              title: '学习摘要',
              status: 'SUCCEEDED',
              start_date: '2026-09-25',
              end_date: '2026-09-25',
              content_markdown: '新版本。[1]',
              included_source_count: 2,
              selected_source_count: 3,
              excluded_source_count: 1,
              exclusion_reasons: {},
              error_code: null,
              error_message: null,
              regenerated_from_id: 'brief-1',
              filters: { category_slugs: [] },
              citations: [],
              source_index: [],
              learning_note: learningNote,
            })
          }
        }
        if (url.includes('/api/briefs/preview')) {
          return jsonResponse({
            sources: [
              { source_id: 'src-1', title: 'note', role: 'PRIMARY_SELECTED', included: true, exclusion_reason: null, privacy_level: 'PRIVATE' },
              { source_id: 'src-2', title: 'secret', role: 'PRIMARY_SELECTED', included: false, exclusion_reason: 'NO_ANALYSIS', privacy_level: 'SENSITIVE' },
            ],
            stats: {
              total_in_range: 2,
              included_for_brief: 1,
              excluded_count: 1,
              exclusion_reasons: { NO_ANALYSIS: 1 },
              extraction_ready_count: 2,
              analysis_ready_count: 1,
              claims_ready_count: 1,
            },
            diagnosis: { code: 'BRIEF_READY', message: '找到 2 条资料，其中 1 条可用于生成简报。' },
          })
        }
        if (url.endsWith('/api/briefs')) {
          return jsonResponse({
            briefs: [{
              id: 'old',
              title: '旧摘要',
              status: 'SUCCEEDED',
              start_date: '2026-09-01',
              end_date: '2026-09-01',
              filters: { category_slugs: ['knowledge'] },
              citations: [],
              source_index: [],
              content_markdown: '旧',
              included_source_count: 1,
              selected_source_count: 1,
              excluded_source_count: 0,
              exclusion_reasons: {},
              error_code: null,
              error_message: null,
              learning_note: learningNote,
            }],
          })
        }
        if (url.includes('/api/sources/src-1')) {
          return jsonResponse({
            source: { id: 'src-1', source_type: 'TEXT', display_name: 'note', original_url: 'https://example.com/a', canonical_url: 'https://example.com/a', content_hash: null, status: 'STORED', created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' },
            asset: null,
            ingestions: [],
            extraction: { run: { status: 'SUCCEEDED' }, document: { title: 'note', extractor_type: 'text', extractor_version: '1', created_at: '2026-09-01T00:00:00Z', plain_text: '沙箱' }, chunks: [{ id: 'chunk-1', heading_path: [], chunk_type: 'text', content: '沙箱' }] },
          })
        }
        return jsonResponse({})
      }),
    )
    render(<BriefPage />)
    expect(await screen.findByRole('button', { name: 'history old' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '预览资料' }))
    expect(await screen.findByText(/可生成 1 条/)).toBeTruthy()
    expect(screen.getByText(/可用于生成笔记/)).toBeTruthy()
    expect(screen.getByText('note')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '生成学习笔记' }))
    expect(await screen.findByText('本期重点')).toBeTruthy()
    expect(screen.getByText('沙箱结论。')).toBeTruthy()
    expect(screen.getByText(/https:\/\/example.com\/a/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Markdown' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'DOCX' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'PDF' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'preset this week' }))
    expect((screen.getByLabelText('brief start') as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    await user.click(screen.getByRole('button', { name: 'preset this month' }))
    await user.click(screen.getByRole('button', { name: 'preset last month' }))
    await user.click(screen.getByRole('button', { name: 'regenerate history brief' }))
    expect(await screen.findByText('本期重点')).toBeTruthy()
    await user.click(screen.getByText('缺失'))
    await user.click(screen.getByRole('button', { name: '生成学习笔记' }))
    expect(await screen.findByText('所选日期与分类范围内没有任何收藏资料。')).toBeTruthy()
  })
})
