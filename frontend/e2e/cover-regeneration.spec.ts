import { expect, test } from '@playwright/test'

const sourceId = '11111111-1111-1111-1111-111111111111'
const oldCover = `/api/sources/${sourceId}/cover-image?v=old`
const candidateCover = `/api/sources/${sourceId}/cover-image?asset_id=candidate-1`

test('cover regeneration requires confirmation and lets the user apply the candidate', async ({ page }) => {
  let generationRequests = 0
  let reviewAction = ''
  await page.route('**/api/library?**', (route) => route.fulfill({
    json: { items: [{
      source_id: sourceId,
      display_name: 'Robotics cover acceptance fixture',
      title: 'Robotics cover acceptance fixture',
      source_type: 'TEXT',
      categories: [],
      preview_image_url: oldCover,
      cover_origin: 'generated',
    }] },
  }))
  await page.route('**/api/sources/*/cover/prompt?**', (route) => route.fulfill({
    json: {
      ok: true,
      prompt: 'Robotics subject with strong contrast, cool blue palette',
      max_prompt_chars: 1500,
      content_usable: true,
      provider: 'MiniMax',
      model: 'image-01',
      budget_used: 54,
      monthly_budget: 100,
      budget_available: true,
      current_cover_url: oldCover,
    },
  }))
  await page.route('**/api/sources/*/cover/status**', (route) => route.fulfill({
    json: { ok: true, lifecycle: 'idle', current_cover_url: oldCover, cover_url: oldCover },
  }))
  await page.route('**/api/sources/*/cover-image**', (route) => route.fulfill({
    contentType: 'image/svg+xml',
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="40"><rect width="64" height="40" fill="#345"/></svg>',
  }))
  await page.route('**/api/sources/*/cover/generate', (route) => {
    generationRequests += 1
    return route.fulfill({ json: {
      ok: true,
      run_id: 'run-1',
      status: 'SUCCEEDED',
      stage: 'SUCCEEDED',
      lifecycle: 'succeeded',
      candidate_asset_id: 'candidate-1',
      candidate_cover_url: candidateCover,
      current_cover_url: oldCover,
      candidate_is_current: false,
    } })
  })
  await page.route('**/api/cover/runs/run-1/review', async (route) => {
    reviewAction = route.request().postDataJSON().action
    await route.fulfill({ json: { ok: true, candidate_review_state: 'APPLIED' } })
  })
  await page.route('**/api/library/trash', (route) => route.fulfill({ json: { items: [] } }))

  await page.goto('/?view=library')
  await page.getByRole('button', { name: '更多操作' }).click()
  await page.getByText('重新生成封面', { exact: true }).click()
  await expect(page.getByRole('button', { name: '确认重新生成' })).toBeVisible()
  await expect(page.getByText(/不是 MiniMax 官方套餐剩余额度/)).toBeVisible()
  expect(generationRequests).toBe(0)

  await page.getByRole('button', { name: '确认重新生成' }).click()
  await expect(page.getByRole('img', { name: '当前封面' })).toBeVisible()
  await expect(page.getByRole('img', { name: '候选封面' })).toBeVisible()
  await expect(page.getByRole('button', { name: '保留旧图' })).toBeVisible()
  await expect(page.getByRole('button', { name: '再生成一张' })).toBeVisible()
  await page.getByRole('button', { name: '使用新图' }).click()
  await expect.poll(() => reviewAction).toBe('use_new')
  expect(generationRequests).toBe(1)
})
