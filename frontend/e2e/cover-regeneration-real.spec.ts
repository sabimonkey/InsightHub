import { execFileSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { backend, python } from './resources'

// Real local API + PostgreSQL + storage; only the external image generator is fake.
// Preserve this AUTOMATION_TEST source and its versioned assets as audit evidence.
test('real cover candidates persist and only explicit review changes current asset', async ({ page, request }, testInfo) => {
  const coverQueue = await (await request.get('/api/cover/queue')).json()
  const { monthly_used, monthly_budget } = coverQueue.summary as { monthly_used: number; monthly_budget: number }
  test.skip(monthly_budget - monthly_used < 3, 'InsightHub local monthly cover safety cap has fewer than three attempts remaining; do not alter USER settings for E2E.')
  const ingest = await (await request.post('/api/ingest/text', {
    data: { text: `e2e-r9-cover-${crypto.randomUUID()}\nA robotics research report describes a blue robotic arm with precise joints and laboratory sensors.` },
  })).json()
  const source = ingest.source.id as string
  const endpoint = `/api/sources/${source}/cover`
  const create = async (key = crypto.randomUUID()) => (await request.post(`${endpoint}/generate`, {
    data: { confirm_send: true, idempotency_key: key, color_scheme: 'cool' },
  })).json()
  const status = async () => (await request.get(`${endpoint}/status`)).json()
  const review = async (run: string, action = 'use_new') => (await request.post(`/api/cover/runs/${run}/review`, { data: { action } })).json()
  const first = await create()
  expect(first.status).toBe('SUCCEEDED')
  expect((await review(first.run_id)).candidate_is_current).toBe(true)
  const initial = await status()
  const before = await (await request.get(`${endpoint}/prompt`)).json()
  let posts = 0
  page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/cover/generate')) posts++ })
  const open = async () => {
    await page.goto(`/?view=library&source=${source}`)
    await page.locator(`[data-source-id="${source}"]`).getByRole('button', { name: '更多操作' }).click()
    await page.getByText('重新生成封面', { exact: true }).click()
  }
  await open()
  await expect(page.getByRole('button', { name: '确认重新生成' })).toBeEnabled()
  await expect(page.getByRole('button', { name: '确认重新生成' })).toBeInViewport()
  expect(posts).toBe(0)
  expect((await status()).run_id).toBe(first.run_id)
  expect((await (await request.get(`${endpoint}/prompt`)).json()).budget_used).toBe(before.budget_used)
  await page.screenshot({ path: testInfo.outputPath('before-confirm.png') })
  await page.getByRole('button', { name: '确认重新生成' }).click()
  await expect(page.getByRole('button', { name: '使用新图' })).toBeEnabled()
  expect(posts).toBe(1)
  const second = await status()
  expect(second.current_cover_url).toBe(initial.current_cover_url)
  expect(second.candidate_asset_id).not.toBe(first.candidate_asset_id)
  await page.screenshot({ path: testInfo.outputPath('candidate-preview.png') })
  await page.getByRole('button', { name: '保留旧图' }).click()
  await expect.poll(async () => (await status()).candidate_review_state).toBe('KEPT_OLD')
  expect((await status()).current_cover_url).toBe(initial.current_cover_url)
  await open()
  await page.getByRole('button', { name: '确认重新生成' }).click()
  await expect(page.getByRole('button', { name: '使用新图' })).toBeEnabled()
  await page.getByRole('button', { name: '再生成一张' }).click()
  expect(posts).toBe(2)
  await page.getByRole('button', { name: '确认并再次生成' }).click()
  await expect.poll(() => posts).toBe(3)
  await expect(page.getByRole('button', { name: '使用新图' })).toBeEnabled()
  const final = await status()
  await page.getByRole('button', { name: '使用新图' }).click()
  await expect.poll(async () => (await status()).candidate_is_current).toBe(true)
  await open() // reload, historical success must show confirmation, not a new result
  await expect(page.getByRole('button', { name: '确认重新生成' })).toBeEnabled()
  await expect(page.getByRole('img', { name: '当前封面' })).toHaveAttribute('src', new RegExp(final.candidate_asset_id))
  expect(posts).toBe(3)
  await page.screenshot({ path: testInfo.outputPath('after-refresh.png') })
  // Independent requests model two tabs applying distinct candidates concurrently.
  const applied = await Promise.all([review(first.run_id), review(final.run_id)])
  expect(applied.every(r => r.ok)).toBe(true)
  await review(final.run_id)
  const sameKey = crypto.randomUUID()
  const repeated = await Promise.all([create(sameKey), create(sameKey)])
  expect(repeated[0].run_id).toBe(repeated[1].run_id)
  const invalid = await (await request.post(`/api/cover/runs/${crypto.randomUUID()}/review`, { data: { action: 'use_new' } })).json()
  expect(invalid.ok).toBe(false)
  expect((await status()).current_cover_url).toContain(final.candidate_asset_id)
  const audit = execFileSync(python, ['-c', `
import json, uuid
from pathlib import Path
from sqlalchemy import select
from app.db.session import get_sessionmaker
from app.models.source_item import SourceItem
from app.models.cover import SourceCoverAsset, CoverGenerationRun
from app.core.config import PROJECT_ROOT
with get_sessionmaker()() as db:
 s=db.get(SourceItem,uuid.UUID('${source}')); assert s.system_scope=='AUTOMATION_TEST'
 assets=list(db.scalars(select(SourceCoverAsset).where(SourceCoverAsset.source_item_id==s.id)))
 current=[a for a in assets if a.is_current]; assert len(current)==1
 assert str(current[0].id)=='${final.candidate_asset_id}'
 assert len({a.relative_path for a in assets})==len(assets)
 assert all((PROJECT_ROOT/a.relative_path).is_file() for a in assets)
 print(json.dumps({'source':str(s.id),'assets':len(assets),'current':str(current[0].id),'historical_files_preserved':True}))
`], { cwd: backend, encoding: 'utf-8' })
  await testInfo.attach('database-audit', { body: audit, contentType: 'application/json' })
})
