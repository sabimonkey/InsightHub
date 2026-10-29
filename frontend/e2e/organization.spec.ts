import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, findInboxSourceId, nav, openSourceDetail, withOwned } from './resources'

test('organize a source into knowledge and promote a project', async ({ page }) => {
  const marker = e2eMarker('organization')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nrecorded fact sentence`)
    await openSourceDetail(page, marker)
    await page.getByRole('button', { name: 'Analyze', exact: true }).click()
    await expect(page.getByText('Summary：结构化摘要')).toBeVisible({ timeout: 20_000 })
    await page.keyboard.press('Escape')
    const sourceId = await findInboxSourceId(page, marker)
    await page.request.put(`/api/sources/${sourceId}/categories`, { data: { add: ['knowledge'], primary: 'knowledge' } })
    await nav(page, '知识库').click()
    await page.getByText('知识', { exact: true }).click()
    await expect(page.locator('.knowledge-card').filter({ hasText: marker })).toBeVisible({ timeout: 20_000 })
    await page.request.put(`/api/sources/${sourceId}/categories`, { data: { add: ['project_discovery'], primary: 'project_discovery' } })
    await page.request.post(`/api/sources/${sourceId}/organize`)
    async function latestCandidateId() {
      const candidates = (await (await page.request.get('/api/project-candidates')).json()) as Array<{ id: string; source_item_id: string }>
      return candidates.find((row) => String(row.source_item_id) === sourceId)?.id
    }
    await expect.poll(latestCandidateId, { timeout: 20_000 }).toBeTruthy()
    const candidateId = await latestCandidateId()
    const promoted = await page.request.post(`/api/project-candidates/${candidateId}/promote`)
    expect(promoted.ok()).toBeTruthy()
    const projects = (await (await page.request.get('/api/projects')).json()) as Array<{ title: string }>
    expect(projects.some((row) => row.name.includes(marker) || row.name === marker)).toBeTruthy()
  })
})
