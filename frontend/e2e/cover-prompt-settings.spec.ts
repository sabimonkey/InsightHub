import { expect, test } from '@playwright/test'

test('MiniMax global cover prompt opens from persisted configuration without generation', async ({ page }, testInfo) => {
  const paidGenerationPosts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/api\/sources\/[^/]+\/cover\/generate$/.test(request.url())) {
      paidGenerationPosts.push(request.url())
    }
  })
  await page.goto('/?view=settings&section=models')
  const minimax = page.locator('.provider-settings-card').filter({ hasText: 'MiniMax' }).first()
  await expect(minimax).toBeVisible()
  await minimax.locator('summary', { hasText: '全局配图 Prompt' }).click()
  await expect(minimax.getByText(/当前修订：\d+ ·/)).toBeVisible()
  await expect(minimax.getByRole('textbox', { name: '全局配图 Prompt' })).toBeVisible()
  await expect(minimax.getByRole('button', { name: '预览最终 Prompt' })).toBeVisible()
  expect(paidGenerationPosts).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('cover-prompt-editor.png'), fullPage: true })
})
