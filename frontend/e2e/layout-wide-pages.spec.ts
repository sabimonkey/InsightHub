import { expect, test } from '@playwright/test'

test('wide pages use expanded container on 1920 viewport', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto('/')
  const collectionWidth = await page.locator('.app-page.collection-capture-page').evaluate((el) => el.getBoundingClientRect().width)
  expect(collectionWidth).toBeGreaterThan(1200)
  expect(collectionWidth).toBeLessThanOrEqual(1680)
  const captureColumns = await page.locator('.collection-capture-page').evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
  expect(captureColumns).toBe(2)

  await page.getByRole('button', { name: '知识库', exact: true }).click()
  const libraryWidth = await page.locator('main.app-page.library-page').evaluate((el) => el.getBoundingClientRect().width)
  expect(libraryWidth).toBeGreaterThan(1200)
})
