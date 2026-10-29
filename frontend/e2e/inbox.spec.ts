import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, openSourceDetail, withOwned } from './resources'

test('add text and see it in the inbox', async ({ page }) => {
  const marker = e2eMarker('inbox')
  await withOwned([marker], async () => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '收集资料' })).toBeVisible()
    await addInboxText(page, marker)
    await expect(page.getByRole('button', { name: new RegExp(`最近资料：.*${marker}`) })).toBeVisible({
      timeout: 20_000,
    })
    await openSourceDetail(page, marker)
    await expect(page.getByText(marker, { exact: false }).last()).toBeVisible()
  })
})
