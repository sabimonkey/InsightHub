import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, nav, openResearchNote, withOwned } from './resources'

test('research note analyze shows progress and summary', async ({ page }) => {
  const marker = e2eMarker('note-analyze')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nrecorded fact sentence`)
    await openResearchNote(page, marker)
    await page.getByRole('button', { name: 'AI 分析' }).click()
    await expect(page.getByText('正在生成学习笔记')).toBeVisible()
    await expect(page.getByText('核心摘要')).toBeVisible({ timeout: 20_000 })
    await page.keyboard.press('Escape')
    await nav(page, '问答').click()
    await expect(page.getByText('新对话')).toBeVisible()
  })
})
