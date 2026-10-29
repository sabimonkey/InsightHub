import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, openResearchNote, withOwned } from './resources'

test('reanalyze keeps note visible and shows progress', async ({ page }) => {
  const marker = e2eMarker('note-reanalyze')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nrecorded fact sentence`)
    await openResearchNote(page, marker)
    await page.getByRole('button', { name: 'AI 分析' }).click()
    await expect(page.getByRole('heading', { name: '核心摘要' })).toBeVisible({ timeout: 25_000 })
    await expect(page.getByRole('button', { name: '重新分析' })).toBeVisible()
    await page.getByRole('button', { name: '重新分析' }).click()
    await expect(page.getByLabel('分析进度')).toBeVisible({ timeout: 8000 })
    await expect(page.getByRole('heading', { name: '核心摘要' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '核心摘要' })).toBeVisible({ timeout: 25_000 })
  })
})
