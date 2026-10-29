import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, openSourceDetail, withOwned } from './resources'

test('discover an arXiv identifier and confirm it', async ({ page }) => {
  const marker = e2eMarker('discovery')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\narXiv: 2609.22978`)
    await openSourceDetail(page, marker)
    await page.getByRole('button', { name: 'Find Original Source' }).click()
    await expect(page.getByText('https://arxiv.org/abs/2609.22978')).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: 'Confirm' }).click()
    await expect(page.getByText('Confirmed Source')).toBeVisible()
  })
})
