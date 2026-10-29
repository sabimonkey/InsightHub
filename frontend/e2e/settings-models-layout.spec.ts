import { expect, test } from '@playwright/test'

test('AI models page shows provider cards and inline model actions', async ({ page }) => {
  await page.goto('/?view=settings&section=models')
  await expect(page.getByRole('heading', { name: 'AI 模型' })).toBeVisible()
  await expect(page.locator('.provider-settings-card-titleline').first()).toBeVisible()
  const providerCard = page.locator('.provider-settings-card').first()
  await expect(providerCard).toBeVisible()
  const modelCard = providerCard.locator('.model-deployment-row').first()
  if (await modelCard.count()) {
    await expect(modelCard.getByRole('button', { name: 'Test Model' })).toBeVisible()
    await expect(modelCard.getByRole('button', { name: 'Delete Model' })).toBeVisible()
    await expect(modelCard.locator('.model-deployment-actions')).toBeVisible()
    const box = await modelCard.locator('.model-deployment-actions').boundingBox()
    expect(box?.width).toBeGreaterThan(100)
  }
  await expect(page.getByText('MiniMax', { exact: true })).toBeVisible()
  const fakeProvider = page.locator('[aria-label="provider Fake"]')
  if (await fakeProvider.count()) {
    await expect(fakeProvider.getByText('模拟测试')).toBeVisible()
    await expect(fakeProvider.getByText('自动化测试模拟')).toBeVisible()
  }
})
