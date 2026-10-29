import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, openSourceDetail, withOwned } from './resources'

test('analyze extracted text with the fake provider', async ({ page }) => {
  const marker = e2eMarker('analysis')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nrecorded fact sentence`)
    await openSourceDetail(page, marker)
    await page.getByRole('button', { name: 'Analyze', exact: true }).click()
    await expect(page.getByText('Summary：结构化摘要')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('heading', { name: 'FACT', exact: true }).locator('..').locator('p').first()).toContainText(marker)
    await page.getByRole('button', { name: '[1]' }).click()
    const cited = page.locator('[id^="chunk-"]').first()
    await expect(cited).toBeVisible()
    await expect(cited).toHaveCSS('background-color', 'rgb(255, 243, 191)')
  })
})
