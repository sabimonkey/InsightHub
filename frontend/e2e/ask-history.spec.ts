import { expect, test } from '@playwright/test'
import { e2eMarker, nav } from './resources'

async function waitTurnDone(page: import('@playwright/test').Page, turnId: string) {
  await expect.poll(async () => {
    const response = await page.request.get(`/api/ask/turns/${turnId}`)
    if (!response.ok()) return false
    const body = (await response.json()) as { status?: string }
    return body.status !== 'PENDING' && body.status !== 'RUNNING'
  }, { timeout: 90_000 }).toBe(true)
}

test('ask session title, delete one, clear all', async ({ page }) => {
  test.setTimeout(120_000)
  const marker = e2eMarker('ask-hist')
  await page.request.post('/api/ask/sessions/clear')
  const session = await page.request.post('/api/ask/sessions', { data: {} })
  expect(session.ok()).toBeTruthy()
  const sessionId = ((await session.json()) as { id: string }).id
  const turn = await page.request.post(`/api/ask/sessions/${sessionId}/turns`, {
    data: { question: `有哪些值得关注的技术特点？ ${marker}`, filters: { scope: 'mine' } },
  })
  expect(turn.ok()).toBeTruthy()
  const turnId = ((await turn.json()) as { id: string }).id
  await waitTurnDone(page, turnId)

  await page.goto('/')
  await nav(page, '问答').click()
  await expect(page.locator('.ask-history-row')).toHaveCount(1, { timeout: 20_000 })
  const sessionRow = page.locator('.ask-history-row').first()
  const titleButton = sessionRow.locator('button.ask-history-item')
  await expect(titleButton).toHaveText(/值得关注的技术特点/)

  await sessionRow.getByRole('button', { name: '对话菜单' }).click()
  await page.getByRole('menuitem', { name: '删除对话' }).click()
  await page.getByRole('dialog', { name: '删除这条对话？' }).getByRole('button', { name: /删\s*除/ }).click()
  await expect(page.locator('.ask-history-row')).toHaveCount(0)

  const session2 = await page.request.post('/api/ask/sessions', { data: {} })
  const session2Id = ((await session2.json()) as { id: string }).id
  const turn2 = await page.request.post(`/api/ask/sessions/${session2Id}/turns`, {
    data: { question: `${marker}-b 第二条测试问题`, filters: { scope: 'mine' } },
  })
  const turn2Id = ((await turn2.json()) as { id: string }).id
  await waitTurnDone(page, turn2Id)
  await page.reload()
  await nav(page, '问答').click()
  await expect(page.locator('.ask-history-row').first()).toBeVisible()

  await page.getByRole('button', { name: '清空历史', exact: true }).click()
  await page.getByRole('dialog', { name: '确定清空全部对话历史？' }).getByRole('button', { name: /清\s*空\s*历\s*史/ }).click()
  await expect(page.locator('.ask-history-row')).toHaveCount(0)
})
