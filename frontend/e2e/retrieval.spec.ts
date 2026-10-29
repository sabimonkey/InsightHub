import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, findInboxSourceId, nav, withOwned } from './resources'

test('search finds the collected source and opens its chunk', async ({ page }) => {
  const marker = e2eMarker('retrieval')
  const other = e2eMarker('retrieval-other')
  await withOwned([marker, other], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nagent sandbox lexical sentence`)
    await addInboxText(page, `${other}\nrobot training corpus note`)
    const sourceId = await findInboxSourceId(page, marker)
    await page.request.put(`/api/sources/${sourceId}/categories`, { data: { add: ['knowledge'], reject: [], primary: 'knowledge' } })
    await nav(page, '搜索').click()
    await page.getByRole('searchbox', { name: '搜索' }).fill(marker)
    await page.getByRole('searchbox', { name: '搜索' }).press('Enter')
    await expect(page.getByText('agent sandbox lexical sentence')).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '阅读摘要' }).first().click()
    await expect(page.locator('.ant-drawer')).toBeVisible({ timeout: 10_000 })
  })
})

test('ask returns a cited answer and opens the source', async ({ page }) => {
  const marker = e2eMarker('ask')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nagent sandbox isolates workloads`)
    await nav(page, '问答').click()
    await page.getByLabel('输入问题').fill(`what does ${marker} say about sandbox`)
    await page.getByRole('button', { name: '提交问题' }).click()
    await expect(page.getByText(`what does ${marker} say about sandbox`)).toBeVisible({ timeout: 20_000 })
    const assistant = page.locator('.ask-bubble-assistant').last()
    const snapshots: string[] = []
    await expect
      .poll(
        async () => {
          const text = (await assistant.innerText()).trim()
          if (text && !snapshots.includes(text)) snapshots.push(text)
          const cited = await page.getByRole('button', { name: '[1]' }).first().isVisible()
          return cited || snapshots.length >= 2
        },
        { timeout: 20_000 },
      )
      .toBe(true)
    await expect(page.getByRole('button', { name: '[1]' }).first()).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: '[1]' }).first().click()
    await expect(page.locator('.ant-drawer')).toBeVisible({ timeout: 10_000 })
  })
})
