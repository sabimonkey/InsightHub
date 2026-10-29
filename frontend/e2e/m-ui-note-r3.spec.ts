import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

test('notes chips remain stationary and the four sections share a stable grid at supported viewports', async ({ page }) => {
  await page.route('**/api/topics', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      { id: 'topic-a', name: 'Agent' },
      { id: 'topic-b', name: 'Robotics' },
      { id: 'topic-c', name: 'Finance' },
      { id: 'topic-d', name: 'Research' },
    ]),
  }))
  await page.route('**/api/categories', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route('**/api/llm/providers', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{ configured: true }]),
  }))
  await page.route('**/api/briefs', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ briefs: [] }),
  }))

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: '笔记' }).click()
  const grid = page.locator('.brief-config-grid')
  await expect(grid.locator('.brief-config-section')).toHaveCount(4)
  const chips = page.locator('.brief-topic-chip')
  await expect(chips).toHaveCount(4)
  const before = await chips.evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect()
    return { text: node.textContent, x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  await chips.nth(1).click()
  await expect(chips.nth(1)).toHaveAttribute('aria-pressed', 'true')
  const selected = await chips.evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect()
    return { text: node.textContent, x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }))
  expect(selected).toEqual(before)
  await expect(chips.nth(1)).not.toContainText('×')
  await chips.nth(1).click()
  await expect(chips.nth(1)).toHaveAttribute('aria-pressed', 'false')
  expect(await chips.allTextContents()).toEqual(before.map((item) => item.text))

  const segmented = page.locator('.brief-detail-segmented')
  await expect(segmented).toBeVisible()
  await expect(segmented.locator('input[type="radio"]')).toHaveCount(3)
  await expect(segmented.getByText('标准')).toBeVisible()
  const selectedSegment = segmented.locator('.ant-segmented-item-selected')
  await expect.poll(() => selectedSegment.evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgb(7, 54, 254)')
  await expect.poll(() => selectedSegment.evaluate((node) => getComputedStyle(node).color)).toBe('rgb(255, 255, 255)')

  const artifactDir = path.resolve(process.cwd(), '..', 'artifacts', 'm-ui-note-r3', 'verification')
  await mkdir(artifactDir, { recursive: true })
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 1024, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    const geometry = await page.evaluate(() => {
      const sections = Array.from(document.querySelectorAll('.brief-config-grid > .brief-config-section'))
        .map((node) => {
          const rect = node.getBoundingClientRect()
          return { left: rect.left, right: rect.right, top: rect.top, width: rect.width }
        })
      const config = document.querySelector('.brief-config-card')!.getBoundingClientRect()
      const result = document.querySelector('.brief-result-area')!.getBoundingClientRect()
      return {
        sections,
        config: { left: config.left, right: config.right, width: config.width },
        result: { left: result.left, right: result.right, width: result.width, top: result.top },
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      }
    })
    expect(geometry.overflow, `page overflow at ${viewport.width}px`).toBe(false)
    expect(Math.abs(geometry.config.left - geometry.result.left)).toBeLessThanOrEqual(1)
    expect(Math.abs(geometry.config.right - geometry.result.right)).toBeLessThanOrEqual(1)
    expect(Math.abs(geometry.config.width - geometry.result.width)).toBeLessThanOrEqual(1)
    expect(geometry.result.top - (await page.locator('.brief-config-card').evaluate((node) => node.getBoundingClientRect().bottom))).toBeGreaterThanOrEqual(20)
    if (viewport.width > 900) {
      expect(Math.abs(geometry.sections[0].left - geometry.sections[2].left)).toBeLessThanOrEqual(1)
      expect(Math.abs(geometry.sections[1].left - geometry.sections[3].left)).toBeLessThanOrEqual(1)
      expect(Math.abs(geometry.sections[0].width - geometry.sections[1].width)).toBeLessThanOrEqual(1)
      expect(Math.abs(geometry.sections[2].width - geometry.sections[3].width)).toBeLessThanOrEqual(1)
    } else {
      expect(geometry.sections[0].top).toBeLessThan(geometry.sections[1].top)
      expect(geometry.sections[1].top).toBeLessThan(geometry.sections[2].top)
      expect(geometry.sections[2].top).toBeLessThan(geometry.sections[3].top)
    }
    await page.screenshot({
      path: path.join(artifactDir, `notes-${viewport.width}x${viewport.height}.png`),
      fullPage: true,
    })
  }
})

test('MiniMax safety cap editor submits the chosen value and reloads server-confirmed state', async ({ page }) => {
  let persisted = 100
  const provider = {
    id: 'automation-minimax',
    name: 'MiniMax',
    provider_type: 'MINIMAX_IMAGE',
    base_url: 'https://api.minimax.cn',
    model: 'image-01',
    is_local: false,
    configured: true,
    credential_configured: true,
    credential_manageable: false,
    enabled: true,
    status: 'READY',
    is_default: false,
    api_key_state: 'CONFIGURED',
    deployments: [],
  }
  await page.route('**/api/llm/providers', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([provider]) }))
  await page.route('**/api/llm/routes', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ routes: [], options: [] }) }))
  await page.route('**/api/embedding/profiles', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ profiles: [] }) }))
  await page.route('**/api/system', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      version: 'test', backend: 'ok', postgres: 'ok', redis: 'ok', worker: 'running',
      alembic: { revision: 'test', ok: true }, raw_storage: 'ok',
      disk: { path: 'test', used: 0, available: 1, warning: false },
      counts: { sources: 0, chunks: 0, claims: 0, embeddings: 0, briefs: 0 },
      optional: { embedding_configured: false, llm_configured: false },
      latest_backup: null, backup_command: 'test',
    }),
  }))
  await page.route('**/api/cover/settings', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON() as { monthly_budget: number }
      expect(body.monthly_budget).toBe(200)
      persisted = body.monthly_budget
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, auto_enabled: false, monthly_budget: persisted, budget_kind: 'insighthub_local_safety_cap', budget_range: { min: 1, max: 500 } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, auto_enabled: false, monthly_budget: persisted, budget_kind: 'insighthub_local_safety_cap', budget_range: { min: 1, max: 500 } }),
    })
  })
  await page.route('**/api/cover/prompt-config', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, prompt: 'Test prompt', revision: 1, version: 'cover-v4', updated_at: null }),
  }))

  await page.goto('/?view=settings&section=models')
  const minimax = page.locator('[aria-label="provider MiniMax"]')
  const input = minimax.getByRole('spinbutton', { name: 'InsightHub 本地安全上限' })
  await expect(input).toHaveAttribute('aria-valuenow', '100')
  await input.fill('200')
  const saved = page.waitForResponse((response) => response.url().endsWith('/api/cover/settings') && response.request().method() === 'PATCH')
  await minimax.getByRole('button', { name: '保存安全上限' }).click()
  const response = await saved
  expect(response.status()).toBe(200)
  await expect(minimax.getByText('InsightHub 本地安全上限已保存：200 次尝试/月')).toBeVisible()
  await expect(input).toHaveAttribute('aria-valuenow', '200')
  const artifactDir = path.resolve(process.cwd(), '..', 'artifacts', 'm-ui-note-r3', 'verification')
  await mkdir(artifactDir, { recursive: true })
  await page.screenshot({ path: path.join(artifactDir, 'minimax-budget-200.png'), fullPage: true })

  await page.reload()
  const reloadedInput = page.locator('[aria-label="provider MiniMax"]').getByRole('spinbutton', { name: 'InsightHub 本地安全上限' })
  await expect(reloadedInput).toHaveAttribute('aria-valuenow', '200')
  expect(persisted).toBe(200)
})
