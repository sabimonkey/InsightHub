import { expect, test } from '@playwright/test'
import { e2eMarker, nav } from './resources'

async function openAskEmpty(page: import('@playwright/test').Page) {
  await page.request.post('/api/ask/sessions/clear')
  await page.goto('/')
  await nav(page, '问答').click()
  await expect(page.getByTestId('ask-empty-pane')).toBeVisible()
}

async function expectInViewport(page: import('@playwright/test').Page, locator: import('@playwright/test').Locator) {
  const box = await locator.boundingBox()
  const vp = page.viewportSize()
  expect(box).toBeTruthy()
  if (!box || !vp) return
  expect(box.y).toBeGreaterThanOrEqual(-2)
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height + 4)
}

test.describe('ask layout isolation', () => {
  test('empty composer visible without page scroll', async ({ page }) => {
    await openAskEmpty(page)
    const scrollY = await page.evaluate(() => window.scrollY)
    expect(scrollY).toBe(0)
    const composer = page.getByRole('textbox', { name: '输入问题' })
    await expect(composer).toBeVisible()
    await expect(page.getByRole('button', { name: '提交问题' })).toBeVisible()
    await expect(page.getByText('基于你的知识库提问')).toBeVisible()
    await expectInViewport(page, composer)
  })

  test('80 history rows do not push composer or body scroll', async ({ page }) => {
    await page.request.post('/api/ask/sessions/clear')
    for (let i = 0; i < 80; i += 1) {
      await page.request.post('/api/ask/sessions', { data: { title: `layout-hist-${String(i).padStart(3, '0')}` } })
    }
    await page.goto('/')
    await nav(page, '问答').click()
    await expect(page.getByTestId('ask-session-list')).toBeVisible()
    const composer = page.getByRole('textbox', { name: '输入问题' })
    await expectInViewport(page, composer)
    const before = await composer.boundingBox()
    const list = page.getByTestId('ask-session-list')
    await list.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    const after = await composer.boundingBox()
    expect(before).toBeTruthy()
    expect(after).toBeTruthy()
    expect(Math.abs((before!.y ?? 0) - (after!.y ?? 0))).toBeLessThan(8)
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 8)
    expect(bodyOverflow).toBe(true)
  })

  test('long history titles do not widen layout', async ({ page }) => {
    const long = `${'超长标题'.repeat(40)} ${e2eMarker('long-title')}`
    await page.request.post('/api/ask/sessions/clear')
    await page.request.post('/api/ask/sessions', { data: { title: long } })
    await page.goto('/')
    await nav(page, '问答').click()
    const main = page.locator('.ask-main')
    const sidebar = page.locator('.ask-sidebar--desktop')
    const mainWidth = await main.evaluate((el) => el.getBoundingClientRect().width)
    const sidebarWidth = await sidebar.evaluate((el) => el.getBoundingClientRect().width)
    expect(mainWidth).toBeGreaterThan(400)
    expect(sidebarWidth).toBeLessThanOrEqual(325)
    await expect(page.locator('.ask-workspace')).toHaveJSProperty('scrollWidth', await page.locator('.ask-workspace').evaluate((el) => el.clientWidth))
  })

  test('active thread scrolls independently with footer composer visible', async ({ page }) => {
    await page.request.post('/api/ask/sessions/clear')
    const session = await page.request.post('/api/ask/sessions', { data: { title: 'layout-active-thread' } })
    const sessionId = ((await session.json()) as { id: string }).id
    for (let i = 0; i < 6; i += 1) {
      await page.request.post(`/api/ask/sessions/${sessionId}/turns`, {
        data: { question: `长问题 ${i} ${'内容'.repeat(120)}`, filters: { scope: 'mine' } },
      })
    }
    await page.goto('/')
    await nav(page, '问答').click()
    await page.getByRole('button', { name: 'layout-active-thread' }).click()
    await expect(page.getByTestId('ask-composer-active')).toBeVisible({ timeout: 30_000 })
    const composer = page.getByTestId('ask-composer-active').getByRole('textbox', { name: '输入问题' })
    await expectInViewport(page, composer)
    const thread = page.getByTestId('ask-message-thread')
    await thread.evaluate((el) => {
      el.scrollTop = 0
    })
    const atTop = await thread.evaluate((el) => el.scrollTop)
    expect(atTop).toBe(0)
    await thread.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    await expectInViewport(page, composer)
  })

  test('left and right scroll positions are independent', async ({ page }) => {
    await page.request.post('/api/ask/sessions/clear')
    for (let i = 0; i < 30; i += 1) {
      await page.request.post('/api/ask/sessions', { data: { title: `scroll-${i}` } })
    }
    const session = await page.request.post('/api/ask/sessions', { data: { title: 'layout-scroll-thread' } })
    const sessionId = ((await session.json()) as { id: string }).id
    for (let i = 0; i < 4; i += 1) {
      await page.request.post(`/api/ask/sessions/${sessionId}/turns`, {
        data: { question: `消息 ${i} ${'段落'.repeat(80)}`, filters: { scope: 'mine' } },
      })
    }
    await page.goto('/')
    await nav(page, '问答').click()
    await page.getByRole('button', { name: 'layout-scroll-thread' }).click()
    await expect(page.getByTestId('ask-message-thread')).toBeVisible({ timeout: 30_000 })
    const composer = page.getByRole('textbox', { name: '输入问题' })
    const before = await composer.boundingBox()
    const list = page.getByTestId('ask-session-list')
    await list.evaluate((el) => {
      el.scrollTop = 400
    })
    const listScroll = await list.evaluate((el) => el.scrollTop)
    expect(listScroll).toBeGreaterThan(50)
    const thread = page.getByTestId('ask-message-thread')
    const threadScrollBefore = await thread.evaluate((el) => el.scrollTop)
    await thread.evaluate((el) => {
      el.scrollTop = 200
    })
    const threadScrollAfter = await thread.evaluate((el) => el.scrollTop)
    expect(threadScrollAfter).toBeGreaterThan(threadScrollBefore)
    const after = await composer.boundingBox()
    expect(Math.abs((before!.y ?? 0) - (after!.y ?? 0))).toBeLessThan(8)
  })

  test('mode switch empty to active to empty', async ({ page }) => {
    await openAskEmpty(page)
    await page.getByRole('textbox', { name: '输入问题' }).fill('布局测试问题')
    await page.getByRole('button', { name: '提交问题' }).click()
    await expect(page.getByTestId('ask-composer-active')).toBeVisible({ timeout: 60_000 })
    await page.getByTestId('ask-new-session').click()
    await expect(page.getByTestId('ask-empty-pane')).toBeVisible()
    await expectInViewport(page, page.getByRole('textbox', { name: '输入问题' }))
  })

  test('mobile drawer history and visible composer', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.request.post('/api/ask/sessions/clear')
    for (let i = 0; i < 15; i += 1) {
      await page.request.post('/api/ask/sessions', { data: { title: `m-${i}` } })
    }
    await page.goto('/')
    await nav(page, '问答').click()
    await page.getByRole('button', { name: '打开对话历史' }).click()
    await expect(page.getByRole('dialog', { name: '对话历史' })).toBeVisible()
    const drawerList = page.locator('.ask-history-drawer .ask-session-list')
    await drawerList.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    await page.keyboard.press('Escape')
    await expectInViewport(page, page.getByRole('textbox', { name: '输入问题' }))
  })
})
