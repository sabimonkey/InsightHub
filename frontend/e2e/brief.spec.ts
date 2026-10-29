import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { addInboxText, e2eMarker, findInboxSourceId, nav, withOwned } from './resources'

test('preview and generate a knowledge brief with a citation', async ({ page }) => {
  const marker = e2eMarker('brief')
  const names = [`${marker}-a`, `${marker}-b`, `${marker}-c`]
  const createdBriefIds: string[] = []
  await withOwned(names, async () => {
    await page.goto('/')
    for (const text of [`${names[0]}\nknowledge sandbox fact alpha`, `${names[1]}\nknowledge sandbox fact beta`, `${names[2]}\nknowledge sandbox fact gamma`]) {
      await addInboxText(page, text)
    }
    const sourceIds: string[] = []
    for (const name of names) {
      sourceIds.push(await findInboxSourceId(page, name))
    }
    for (const sourceId of sourceIds) {
      await page.request.post(`/api/sources/${sourceId}/analyze`)
    }
    await expect.poll(async () => {
      const checks = await Promise.all(sourceIds.map(async (sourceId) => page.request.get(`/api/sources/${sourceId}/analysis`)))
      const bodies = await Promise.all(checks.map(async (response) => response.json() as Promise<{ run?: { status?: string } }>))
      return bodies.every((body) => body.run?.status === 'SUCCEEDED' || body.run?.status === 'PARTIAL')
    }, { timeout: 20_000 }).toBe(true)
    const created = await page.request.post('/api/topics', { data: { alias: marker } })
    expect(created.ok()).toBeTruthy()
    for (const sourceId of sourceIds) {
      await page.request.put(`/api/sources/${sourceId}/topics`, { data: { add: [marker], reject_ids: [] } })
    }
    await nav(page, '笔记').click()
    const configCard = page.locator('.brief-config-card')
    await expect(configCard).toBeVisible()
    await expect(configCard.locator('.brief-config-section')).toHaveCount(4)
    await expect(configCard.locator('.ant-card')).toHaveCount(0)
    const sectionTitles = await configCard.locator('.brief-config-section-title').allTextContents()
    expect(sectionTitles).toEqual(['时间范围', '资料范围', '主题与生成设置', '资料预览'])
    const cardSpacing = await page.evaluate(() => {
      const config = document.querySelector('.brief-config-card')!.getBoundingClientRect()
      const result = document.querySelector('.brief-result-area')!.getBoundingClientRect()
      return result.top - config.bottom
    })
    expect(cardSpacing).toBeGreaterThanOrEqual(20)
    await page.getByText('知识', { exact: true }).click()
    await page.getByRole('button', { name: 'preset this month' }).click()
    await page.getByRole('textbox', { name: 'topic search' }).fill(marker)
    await page.getByRole('button', { name: marker }).click()
    await page.getByRole('button', { name: '预览资料' }).click()
    await expect(page.locator('.brief-config-grid').getByText(/可生成 \d+ 条/)).toBeVisible()
    const createResponsePromise = page.waitForResponse((response) => response.url().endsWith('/api/briefs') && response.request().method() === 'POST')
    await page.getByRole('button', { name: '生成学习笔记' }).click()
    const createResponse = await createResponsePromise
    expect(createResponse.ok()).toBeTruthy()
    const createdBrief = (await createResponse.json()) as { id: string; job_id?: string | null }
    createdBriefIds.push(createdBrief.id)
    if (createdBrief.job_id) expect(createdBrief.job_id).toBe(createdBrief.id)
    await expect(page.getByText('学习摘要')).toBeVisible({ timeout: 20_000 })
    const regenerateResponsePromise = page.waitForResponse((response) => response.url().includes('/regenerate') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'regenerate history brief' }).click()
    const regenerateResponse = await regenerateResponsePromise
    expect(regenerateResponse.ok()).toBeTruthy()
    createdBriefIds.push(((await regenerateResponse.json()) as { id: string }).id)
    await expect(page.getByText('学习摘要')).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '[1]' }).first().click()
    await expect(page.locator('[id^="chunk-"]').first()).toBeVisible()
    const current = page.getByRole('link', { name: 'Markdown' })
    const href = await current.getAttribute('href')
    const exported = await page.request.get(href ?? '')
    expect(exported.ok()).toBeTruthy()
    const body = await exported.text()
    expect(body).toContain('## Sources')
    expect(body).toContain('[1]')
    await page.reload()
    await expect(page.getByText('学习摘要')).toBeVisible({ timeout: 10_000 })
    const persisted = await page.request.get(`/api/briefs/${createdBriefIds[1]}`)
    expect(persisted.ok()).toBeTruthy()
    const persistedBrief = (await persisted.json()) as { status: string; content_markdown: string }
    expect(persistedBrief.status).toBe('SUCCEEDED')
    expect(persistedBrief.content_markdown).toContain('# 学习摘要')
    expect(persistedBrief.content_markdown).toContain('## Sources')
    const artifactDir = path.resolve(process.cwd(), '..', 'artifacts', 'm-ui-note-r3')
    await mkdir(artifactDir, { recursive: true })
    for (const viewport of [
      { width: 1920, height: 1080 },
      { width: 1440, height: 900 },
      { width: 1366, height: 768 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport)
      const overflow = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth > window.innerWidth,
        elements: Array.from(document.querySelectorAll<HTMLElement>('body *'))
          .filter((element) => {
            const rect = element.getBoundingClientRect()
            return rect.width > 0 && (rect.left < -1 || rect.right > window.innerWidth + 1)
          })
          .slice(0, 8)
          .map((element) => ({ selector: `${element.tagName.toLowerCase()}.${String(element.className).replace(/\s+/g, '.')}`, left: Math.round(element.getBoundingClientRect().left), right: Math.round(element.getBoundingClientRect().right), width: Math.round(element.getBoundingClientRect().width) })),
      }))
      expect(overflow.page, `horizontal overflow at ${viewport.width}px: ${JSON.stringify(overflow.elements)}`).toBe(false)
      const dates = await page.locator('.brief-date-row .ant-input').evaluateAll((inputs) => inputs.map((input) => (input as HTMLElement).getBoundingClientRect().width))
      expect(dates).toHaveLength(2)
      expect(Math.abs(dates[0] - dates[1])).toBeLessThanOrEqual(2)
      await page.screenshot({ path: path.join(artifactDir, `notes-workspace-${viewport.width}x${viewport.height}.png`), fullPage: true })
    }
    for (const briefId of createdBriefIds) {
      const cleanup = await page.request.delete(`/api/briefs/${briefId}`)
      expect(cleanup.ok()).toBeTruthy()
    }
  }, [marker])
})

test('clear learning note history only after confirmation', async ({ page }) => {
  let rows = [{
    id: 'automation-note-clear',
    title: '隔离笔记清理测试',
    status: 'SUCCEEDED',
    start_date: '2026-10-01',
    end_date: '2026-10-28',
    completed_at: '2026-10-28T10:00:00Z',
    content_markdown: '# 隔离笔记',
    learning_note: { title: '隔离笔记清理测试', highlights: [], theme_notes: [], sections: {}, follow_ups: [] },
    included_source_count: 0,
    selected_source_count: 0,
    excluded_source_count: 0,
    exclusion_reasons: {},
    error_code: null,
    error_message: null,
    filters: { category_slugs: [] },
    citations: [],
    source_index: [],
  }]
  const calls: string[] = []
  await page.route('**/api/briefs', async (route) => {
    const request = route.request()
    calls.push(request.method())
    if (request.method() === 'DELETE') {
      rows = []
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted_count: 1 }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ briefs: rows }) })
  })

  await page.goto('/')
  await nav(page, '笔记').click()
  await expect(page.getByRole('button', { name: 'history automation-note-clear' })).toBeVisible()
  await page.getByRole('button', { name: '清空历史' }).click()
  await expect(page.getByText(/将删除所有学习笔记历史及其正文/)).toBeVisible()
  expect(calls).not.toContain('DELETE')
  await page.getByRole('button', { name: '清空历史' }).last().click()
  await expect(page.getByText('暂无学习笔记历史')).toBeVisible()
  expect(calls.filter((method) => method === 'DELETE')).toHaveLength(1)
  await page.reload()
  await nav(page, '笔记').click()
  await expect(page.getByText('暂无学习笔记历史')).toBeVisible()
})

test('generate a topic synthesis with citations', async ({ page }) => {
  const marker = e2eMarker('topic')
  const names = [`${marker}-a`, `${marker}-b`]
  await withOwned(names, async () => {
    await page.goto('/')
    for (const text of [`${names[0]}\nagent sandbox lowers cost`, `${names[1]}\nagent sandbox raises cost`]) {
      await addInboxText(page, text)
    }
    const sourceIds = await Promise.all(names.map(async (name) => findInboxSourceId(page, name)))
    for (const sourceId of sourceIds) await page.request.post(`/api/sources/${sourceId}/analyze`)
    await expect.poll(async () => {
      const checks = await Promise.all(sourceIds.map(async (sourceId) => page.request.get(`/api/sources/${sourceId}/analysis`)))
      const bodies = await Promise.all(checks.map(async (response) => response.json() as Promise<{ run?: { status?: string } }>))
      return bodies.every((body) => body.run?.status === 'SUCCEEDED' || body.run?.status === 'PARTIAL')
    }, { timeout: 20_000 }).toBe(true)
    const created = await page.request.post('/api/topics', { data: { alias: marker } })
    const topic = (await created.json()) as { id: string }
    for (const sourceId of sourceIds) {
      await page.request.put(`/api/sources/${sourceId}/topics`, { data: { add: [marker], reject_ids: [] } })
    }
    const synthesis = await page.request.post(`/api/topics/${topic.id}/synthesize`, { data: { detail_level: 'STANDARD' } })
    const body = (await synthesis.json()) as { id: string; status: string }
    await expect.poll(async () => ((await (await page.request.get(`/api/topic-syntheses/${body.id}`)).json()) as { status: string }).status).toBe('SUCCEEDED')
    const detail = (await (await page.request.get(`/api/topic-syntheses/${body.id}`)).json()) as { content_markdown: string; citations: unknown[] }
    expect(detail.content_markdown).toContain('[1]')
    expect(detail.citations.length).toBeGreaterThan(0)
  }, [marker])
})
