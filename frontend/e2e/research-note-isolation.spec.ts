import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, findInboxSourceId, nav, withOwned } from './resources'

test('completed source A stays visible while source B analysis runs', async ({ page }) => {
  const markerA = e2eMarker('iso-a')
  const markerB = e2eMarker('iso-b')
  await withOwned([markerA, markerB], async () => {
    await page.goto('/')
    await addInboxText(page, `${markerA}\nAlpha recorded fact for isolation test.`)
    await addInboxText(page, `${markerB}\nBeta recorded fact for isolation test.`)

    await nav(page, '知识库').click()
    const sourceIdA = await findInboxSourceId(page, markerA)
    const sourceIdB = await findInboxSourceId(page, markerB)
    const cardA = page.locator(`[data-source-id="${sourceIdA}"]`)
    const cardB = page.locator(`[data-source-id="${sourceIdB}"]`)
    await expect(cardA).toBeVisible({ timeout: 20_000 })
    await expect(cardB).toBeVisible({ timeout: 20_000 })

    await cardA.click()
    await page.getByRole('button', { name: 'AI 分析' }).click()
    await expect(page.getByText('核心摘要')).toBeVisible({ timeout: 25_000 })
    await page.keyboard.press('Escape')

    await cardB.click()
    await page.getByRole('button', { name: 'AI 分析' }).click()
    await expect(page.getByText('正在生成学习笔记')).toBeVisible()
    await page.keyboard.press('Escape')

    await cardA.click()
    await expect(page.locator('.drawer-title')).toContainText(markerA)
    await expect(page.locator('.drawer-title')).not.toContainText(markerB)
    await expect(page.getByText('正在生成学习笔记')).not.toBeVisible()
    await expect(page.getByText('核心摘要')).toBeVisible()
  })
})

test('library card opens the correct source note', async ({ page }) => {
  const marker = e2eMarker('lib-open')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nLibrary card open test content.`)
    await nav(page, '知识库').click()
    await page.locator('.knowledge-card').filter({ hasText: marker }).click()
    await expect(page.locator('.drawer-title')).toContainText(marker)
  })
})
