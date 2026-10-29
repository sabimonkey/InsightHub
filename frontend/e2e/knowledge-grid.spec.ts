import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, nav, withOwned } from './resources'

test.describe('knowledge grid layout', () => {
  test('1920 viewport shows five columns', async ({ page }) => {
    const marker = e2eMarker('grid-5')
    await page.setViewportSize({ width: 1920, height: 1080 })
    await withOwned([marker], async () => {
      await page.goto('/')
      await addInboxText(page, `${marker}\ngrid layout sample`)
      await nav(page, '知识库').click()
      const grid = page.getByTestId('knowledge-grid')
      await expect(grid).toBeVisible()
      const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
      expect(columns).toBe(5)
      await expect(page.locator('.knowledge-card').first()).toBeVisible()
      await expect(page.locator('.knowledge-card-media').first()).toBeVisible()
    })
  })

  test('1366 viewport uses three columns', async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 })
    await page.goto('/')
    await nav(page, '知识库').click()
    const grid = page.getByTestId('knowledge-grid')
    const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
    expect(columns).toBe(3)
  })

  test('1500 viewport uses four columns', async ({ page }) => {
    await page.setViewportSize({ width: 1500, height: 900 })
    await page.goto('/')
    await nav(page, '知识库').click()
    const grid = page.getByTestId('knowledge-grid')
    const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
    expect(columns).toBe(4)
  })
})
