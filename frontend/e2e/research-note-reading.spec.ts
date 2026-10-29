import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, openResearchNote, withOwned } from './resources'

const readingFixture = {
  source_id: 'mock-source',
  title: 'E2E 学习笔记',
  source_type: 'TEXT',
  source_type_label: '文本',
  author: null,
  original_url: 'https://example.com/e2e',
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
  analysis: { provider: 'Fake', model_name: 'fake', prompt_version: '1.1.0', is_cloud: false },
  reading: {
    core_summary: { paragraphs: ['E2E 核心摘要段落。'] },
    core_points: ['E2E 核心要点一。'],
    inferences_and_open: null,
    source_and_evidence: {
      source_type_label: '文本',
      author: null,
      collected_at: '2026-10-13T08:00:00Z',
      original_url: 'https://example.com/e2e',
      evidence_summary: { verified_count: 1, items: [] },
    },
  },
}

test('completed research note shows reading surface', async ({ page }) => {
  const marker = e2eMarker('note-reading')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, marker)
    const sourceId = await page.evaluate(async (m) => {
      const inbox = await fetch('/api/inbox?filter=all&page=1&page_size=50')
      const body = (await inbox.json()) as { items: Array<{ source_id: string; display_name: string }> }
      const row = body.items.find((item) => item.display_name === m || item.display_name?.startsWith(m))
      return row?.source_id
    }, marker)
    expect(sourceId).toBeTruthy()
    await page.route(`**/api/sources/${sourceId}/note`, async (route) => {
      await route.fulfill({ json: { ...readingFixture, source_id: sourceId, title: marker } })
    })
    await openResearchNote(page, marker)
    await expect(page.getByRole('heading', { name: '核心摘要' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '核心要点' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '来源与依据' })).toBeVisible()
    await expect(page.getByText('E2E 核心摘要段落。')).toBeVisible()
    await expect(page.getByText('Provider', { exact: false })).not.toBeVisible()
  })
})

test('pending research note shows waiting copy and no export', async ({ page }) => {
  const marker = e2eMarker('note-pending')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, marker)
    const sourceId = await page.evaluate(async (m) => {
      const inbox = await fetch('/api/inbox?filter=all&page=1&page_size=50')
      const body = (await inbox.json()) as { items: Array<{ source_id: string; display_name: string }> }
      const row = body.items.find((item) => item.display_name === m || item.display_name?.startsWith(m))
      return row?.source_id
    }, marker)
    await page.route(`**/api/sources/${sourceId}/note`, async (route) => {
      await route.fulfill({
        json: {
          ...readingFixture,
          source_id: sourceId,
          title: marker,
          analysis_status: '等待中',
          analysis_status_code: 'PENDING',
          analysis_latest_status_code: 'PENDING',
          export_enabled: false,
          reading: null,
        },
      })
    })
    await openResearchNote(page, marker)
    await expect(page.getByText('正在生成学习笔记')).toBeVisible()
    await expect(page.getByRole('button', { name: '复制 Markdown' })).not.toBeVisible()
  })
})
