import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, findInboxSourceId, nav, withOwned } from './resources'

test('soft delete and restore source from library trash', async ({ page }) => {
  const marker = e2eMarker('trash')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\ntrash lifecycle sample`)
    const sourceId = await findInboxSourceId(page, marker)
    await nav(page, '知识库').click()
    const card = page.locator(`[data-source-id="${sourceId}"]`)
    await expect(card).toBeVisible({ timeout: 20_000 })
    await card.getByRole('button', { name: '更多操作' }).click()
    await page.getByRole('menuitem', { name: '删除资料' }).click()
    const trashPost = page.waitForResponse((response) => response.url().includes(`/api/sources/${sourceId}/trash`) && response.request().method() === 'POST')
    await page.getByRole('button', { name: '移至最近删除' }).click()
    await trashPost
    await expect(page.getByText('已移至最近删除')).toBeVisible()
    await expect(card).toHaveCount(0)
    await page.locator('main.library-page').getByRole('button', { name: '最近删除' }).click()
    await expect(page.getByTestId('library-trash-grid')).toBeVisible()
    const trashCard = page.locator(`[data-testid="library-trash-grid"] [data-source-id="${sourceId}"]`)
    await expect(trashCard).toBeVisible({ timeout: 15_000 })
    const restoreBtn = trashCard.getByRole('button', { name: '恢复资料' })
    await expect(restoreBtn).toBeVisible({ timeout: 15_000 })
    const restorePost = page.waitForResponse((response) => response.url().includes(`/api/sources/${sourceId}/restore`) && response.request().method() === 'POST')
    await restoreBtn.click()
    await restorePost
    await expect(page.locator(`[data-testid="knowledge-grid"] [data-source-id="${sourceId}"]`)).toBeVisible({ timeout: 20_000 })
  })
})
