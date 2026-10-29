import { expect, test } from '@playwright/test'
test.describe('settings hierarchical nav', () => {
  test('defaults to overview and switches sections', async ({ page }) => {
    await page.goto('/?view=settings')
    await expect(page.getByTestId('settings-layout')).toBeVisible()
    await expect(page.getByRole('heading', { name: '设置概览' })).toBeVisible()
    await expect(page.getByText('当前配置摘要')).toBeVisible()
    await page.locator('button.settings-nav-item', { hasText: 'AI 模型' }).click()
    await expect(page.getByRole('heading', { name: 'AI 模型' })).toBeVisible()
    await page.locator('button.settings-nav-item', { hasText: '工作流路由' }).click()
    await expect(page.getByLabel('资料分析 route')).toBeVisible()
    await page.locator('button.settings-nav-item', { hasText: '运行状态' }).click()
    await expect(page.getByLabel('system status')).toBeVisible()
  })

  test('section persists in URL after refresh', async ({ page }) => {
    await page.goto('/?view=settings&section=routes')
    await expect(page.getByLabel('资料分析 route')).toBeVisible()
    await page.reload()
    await expect(page.getByLabel('资料分析 route')).toBeVisible()
  })

  test('does not expose api keys in dom', async ({ page }) => {
    await page.goto('/?view=settings&section=models')
    const html = await page.content()
    expect(html.toLowerCase()).not.toMatch(/sk-[a-z0-9]{20,}/)
  })
})
