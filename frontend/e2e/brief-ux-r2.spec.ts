import { expect, test } from '@playwright/test'
import { nav } from './resources'

test.describe('M-BRIEF-UX-R2 brief state isolation', () => {
  test('history reading does not override draft month generate', async ({ page }) => {
    const septId = '00000000-0000-4000-8000-000000000901'
    const octId = '00000000-0000-4000-8000-000000001001'
    let lastCreateBody: Record<string, unknown> | null = null
    let previewCalls = 0

    await page.addInitScript(() => {
      const fixed = new Date('2026-10-22T12:00:00')
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(globalThis as any).Date = class extends Date {
        constructor(...args: ConstructorParameters<typeof Date>) {
          if (args.length === 0) super(fixed.getTime())
          else super(...args)
        }
        static now() {
          return fixed.getTime()
        }
      }
    })

    await page.route('**/api/briefs**', async (route) => {
      const url = route.request().url()
      const method = route.request().method()
      if (url.endsWith('/api/briefs') && method === 'GET') {
        await route.fulfill({
          json: {
            briefs: [{
              id: septId,
              title: null,
              status: 'SUCCEEDED',
              start_date: '2026-09-01',
              end_date: '2026-09-30',
              included_source_count: 3,
              selected_source_count: 3,
              excluded_source_count: 0,
              exclusion_reasons: {},
              error_code: null,
              error_message: null,
              filters: { category_slugs: [] },
              citations: [],
              source_index: [],
              content_markdown: 'sept',
              learning_note: { title: '九月笔记', highlights: ['九月历史正文'], theme_notes: [], sections: {}, follow_ups: [] },
            }],
          },
        })
        return
      }
      if (url.includes(`/api/briefs/${septId}`) && method === 'GET') {
        await route.fulfill({
          json: {
            id: septId,
            status: 'SUCCEEDED',
            start_date: '2026-09-01',
            end_date: '2026-09-30',
            included_source_count: 3,
            selected_source_count: 3,
            excluded_source_count: 0,
            exclusion_reasons: {},
            error_code: null,
            error_message: null,
            filters: { category_slugs: [] },
            citations: [],
            source_index: [],
            content_markdown: 'sept',
            learning_note: { title: '九月笔记', highlights: ['九月历史正文'], theme_notes: [], sections: {}, follow_ups: [] },
          },
        })
        return
      }
      if (url.endsWith('/api/briefs/preview') && method === 'POST') {
        previewCalls += 1
        const body = route.request().postDataJSON() as { start_date: string }
        expect(body.start_date).toBe('2026-10-01')
        await route.fulfill({
          json: {
            sources: [],
            stats: { total_in_range: 34, included_for_brief: 26, exclusion_reasons: {} },
            diagnosis: { code: 'OK', message: 'ok' },
          },
        })
        return
      }
      if (url.endsWith('/api/briefs') && method === 'POST') {
        lastCreateBody = route.request().postDataJSON() as Record<string, unknown>
        expect(lastCreateBody.start_date).toBe('2026-10-01')
        expect(lastCreateBody.end_date).toBe('2026-10-22')
        await route.fulfill({
          json: {
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
            filters: { category_slugs: [] },
            citations: [],
            source_index: [],
            content_markdown: 'oct',
            learning_note: { title: '十月笔记', highlights: ['十月新生成正文'], theme_notes: [], sections: {}, follow_ups: [] },
          },
        })
        return
      }
      if (url.includes(`/api/briefs/${octId}`)) {
        await route.fulfill({
          json: {
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
            filters: { category_slugs: [] },
            citations: [],
            source_index: [],
            content_markdown: 'oct',
            learning_note: { title: '十月笔记', highlights: ['十月新生成正文'], theme_notes: [], sections: {}, follow_ups: [] },
          },
        })
        return
      }
      await route.continue()
    })

    await page.goto('/')
    await nav(page, '笔记').click()
    await page.getByRole('button', { name: `history ${septId}` }).click()
    await expect(page.getByText('九月历史正文')).toBeVisible()
    await expect(page.getByLabel('reading context history')).toBeVisible()

    await page.getByRole('button', { name: 'preset this month' }).click()
    await expect(page.getByLabel('brief start')).toHaveValue('2026-10-01')
    await expect(page.getByText('九月历史正文')).toBeVisible()

    await page.getByRole('button', { name: '预览资料' }).click()
    expect(previewCalls).toBeGreaterThan(0)

    await page.getByRole('button', { name: '生成学习笔记' }).click()
    await expect(page.getByText('十月新生成正文')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByLabel('reading context generation')).toBeVisible()
    expect(lastCreateBody).toBeTruthy()
  })
})
