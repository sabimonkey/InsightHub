import { expect, test } from '@playwright/test'

test('collection cards exchange surfaces while tabs remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/')

  const addPanel = page.getByTestId('add-source-panel')
  const recentPanel = page.locator('.recent-sources-section')
  await expect(addPanel).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  await expect(recentPanel).toHaveCSS('background-color', 'rgb(23, 23, 23)')
  const recentRow = page.locator('.recent-source-row').first()
  if (await recentRow.count()) await expect(recentRow).toHaveCSS('background-color', 'rgb(38, 38, 38)')

  await page.getByRole('tab', { name: '文本' }).click()
  await expect(page.getByRole('textbox', { name: '文本' })).toBeVisible()
  await page.getByRole('tab', { name: '文件' }).click()
  await expect(page.getByText('拖拽文件到这里，或点击选择。可以一次选择多个文件。')).toBeVisible()
  await page.getByRole('tab', { name: 'URL' }).click()
  await expect(page.getByRole('textbox', { name: 'URL' })).toBeVisible()

  const geometry = await page.evaluate(() => {
    const add = document.querySelector<HTMLElement>('.collection-add-panel--centered')!
    const recent = document.querySelector<HTMLElement>('.recent-sources-section')!
    const row = document.querySelector<HTMLElement>('.recent-source-row')!
    return {
      addRadius: getComputedStyle(add).borderRadius,
      recentRadius: getComputedStyle(recent).borderRadius,
      rowRadius: getComputedStyle(row).borderRadius,
    }
  })
  expect(geometry.addRadius).toBe('24px')
  expect(geometry.recentRadius).toBe('24px')

  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect(addPanel).toBeVisible()
    await expect(recentPanel).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
    expect(overflow).toBe(false)
  }
  await page.setViewportSize({ width: 1366, height: 768 })
  if (await recentRow.count()) {
    await recentRow.click()
    await expect(page).toHaveURL(/view=library/)
  }
})

test('ask empty state is centered and adaptively raised without changing chat layout', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.request.post('/api/ask/sessions/clear')
  await page.goto('/?view=ask')
  const pane = page.getByTestId('ask-empty-pane')
  await expect(pane).toBeVisible()
  const geometry = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>('.ask-main')!
    const header = document.querySelector<HTMLElement>('.ask-header')!
    const pane = document.querySelector<HTMLElement>('.ask-empty-pane')!
    const group = document.querySelector<HTMLElement>('.ask-welcome')!
    const input = document.querySelector<HTMLElement>('.ask-composer-shell--welcome')!
    const suggestions = document.querySelector<HTMLElement>('.ask-suggestions')!
    const rect = (element: HTMLElement) => {
      const { x, y, right, bottom, width, height } = element.getBoundingClientRect()
      return { x, y, right, bottom, width, height }
    }
    return {
      main: rect(main),
      header: rect(header),
      pane: rect(pane),
      group: rect(group),
      input: rect(input),
      suggestions: rect(suggestions),
      mainRadius: getComputedStyle(main).borderRadius,
    }
  })
  expect(geometry.group.x + geometry.group.width / 2).toBeCloseTo(geometry.pane.x + geometry.pane.width / 2, 0)
  expect(geometry.group.y).toBeGreaterThanOrEqual(geometry.header.bottom)
  expect(geometry.group.y + geometry.group.height / 2).toBeLessThanOrEqual(geometry.pane.y + geometry.pane.height / 2 - 24)
  expect(geometry.input.right).toBeLessThanOrEqual(geometry.main.right)
  expect(geometry.suggestions.bottom).toBeLessThanOrEqual(geometry.main.bottom)
  expect(geometry.mainRadius).toBe('24px')

  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(viewport)
    const layout = await page.evaluate(() => {
      const main = document.querySelector<HTMLElement>('.ask-main')!.getBoundingClientRect()
      const pane = document.querySelector<HTMLElement>('.ask-empty-pane')!.getBoundingClientRect()
      const group = document.querySelector<HTMLElement>('.ask-welcome')!.getBoundingClientRect()
      const header = document.querySelector<HTMLElement>('.ask-header')!.getBoundingClientRect()
      return { main, pane, group, header, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth }
    })
    expect(layout.overflow).toBe(false)
    expect(layout.group.x + layout.group.width / 2).toBeCloseTo(layout.pane.x + layout.pane.width / 2, 0)
    expect(layout.group.y).toBeGreaterThanOrEqual(layout.header.bottom)
    expect(layout.group.bottom).toBeLessThanOrEqual(layout.main.bottom)
  }

  await page.getByRole('button', { name: /总结我最近收藏的 Agent 相关资料/ }).click()
  await expect(page.getByRole('textbox', { name: '输入问题' })).toHaveValue(/总结我最近收藏的 Agent/)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('textbox', { name: '输入问题' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
})

test('notes page uses compact dates, light quick controls, and consistent panel radii', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/?view=briefs')
  await expect(page.getByRole('button', { name: '笔记', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '笔记', exact: true })).toBeVisible()

  const dateWidths = await page.evaluate(() => {
    const start = document.querySelector<HTMLInputElement>('[aria-label="brief start"]')!
    const end = document.querySelector<HTMLInputElement>('[aria-label="brief end"]')!
    const widths = [start, end].map((input) => input.getBoundingClientRect().width)
    const preset = document.querySelector<HTMLElement>('.brief-preset-row .ant-btn-default')!
    return {
      widths,
      dateRow: document.querySelector<HTMLElement>('.brief-date-row')!.getBoundingClientRect().toJSON(),
      startBorder: getComputedStyle(start).borderRadius,
      presetBorder: getComputedStyle(preset).borderColor,
      presetBackground: getComputedStyle(preset).backgroundColor,
      radii: ['.brief-sidebar', '.brief-article'].map((selector) => {
        const element = document.querySelector<HTMLElement>(selector)
        return element ? getComputedStyle(element).borderRadius : null
      }),
    }
  })
  expect(dateWidths.widths[0]).toBeGreaterThanOrEqual(160)
  expect(dateWidths.widths[0]).toBeLessThanOrEqual(190)
  expect(dateWidths.widths[1]).toBe(dateWidths.widths[0])
  expect(dateWidths.radii).toEqual(['24px', null])
  expect(dateWidths.presetBorder).toBe('rgba(0, 0, 0, 0)')
  await page.getByRole('button', { name: 'preset this month' }).click()
  await expect(page.locator('.brief-preset-row .brief-preset-selected')).toBeVisible()

  const quickButton = page.locator('.brief-preset-row .brief-preset-option').first()
  const beforeHover = await quickButton.evaluate((element) => getComputedStyle(element).backgroundColor)
  await quickButton.hover()
  await expect.poll(() => quickButton.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(beforeHover)

  await page.setViewportSize({ width: 390, height: 844 })
  const mobile = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    dateRow: document.querySelector<HTMLElement>('.brief-date-row')!.getBoundingClientRect().toJSON(),
    start: document.querySelector<HTMLInputElement>('[aria-label="brief start"]')!.getBoundingClientRect().toJSON(),
    end: document.querySelector<HTMLInputElement>('[aria-label="brief end"]')!.getBoundingClientRect().toJSON(),
  }))
  expect(mobile.overflow).toBe(false)
  expect(mobile.end.y).toBeGreaterThanOrEqual(mobile.start.y)
  expect(mobile.end.right).toBeLessThanOrEqual(390)
})
