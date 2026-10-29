import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, withOwned } from './resources'

test.describe('collection quick capture', () => {
  test('centered add panel without split workspace', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await page.goto('/')
    await expect(page.getByTestId('add-source-panel')).toBeVisible()
    await expect(page.getByTestId('collection-split-left')).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'URL' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '文本' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '文件' })).toBeVisible()
    await expect(page.getByText('最近收集')).toBeVisible()
  })

  test('recent list updates after add and deep links to library', async ({ page }) => {
    const marker = e2eMarker('capture-recent')
    await withOwned([marker], async () => {
      await page.goto('/')
      await addInboxText(page, `${marker}\nrecent capture row`)
      await expect(page.getByRole('button', { name: new RegExp(`最近资料：.*${marker}`) })).toBeVisible({ timeout: 15_000 })
      await page.getByRole('button', { name: new RegExp(`最近资料：.*${marker}`) }).click()
      await expect(page).toHaveURL(/view=library/)
      await expect(page).toHaveURL(/source=[0-9a-f-]{36}/)
      await expect(page.getByTestId('knowledge-grid')).toBeVisible()
      await expect(page.locator('[data-source-id]').filter({ hasText: marker })).toBeVisible()
    })
  })

  test('view all opens library', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '查看全部资料' }).click()
    await expect(page.getByTestId('knowledge-grid')).toBeVisible()
  })
})
