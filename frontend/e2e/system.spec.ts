import { execFileSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { addInboxText, backend, e2eMarker, openSourceDetail, python, withOwned } from './resources'

function markFailed(marker: string) {
  const script = `
from sqlalchemy import select
from app.db.session import get_sessionmaker
from app.models.analysis import AnalysisRun
from app.models.source_item import SourceItem
session = get_sessionmaker()()
try:
    source = session.scalar(select(SourceItem).where(SourceItem.display_name.like(${JSON.stringify(marker + '%')})))
    run = None if source is None else session.scalar(select(AnalysisRun).where(AnalysisRun.source_item_id == source.id, AnalysisRun.is_current.is_(True)))
    if run is None:
        raise SystemExit(2)
    run.status = "FAILED"
    run.error_code = "WORKER_INTERRUPTED"
    session.commit()
finally:
    session.close()
`
  execFileSync(python, ['-c', script], {
    cwd: backend,
    stdio: 'inherit',
  })
}

test('system status shows core services and version', async ({ page }) => {
  await page.goto('/?view=settings&section=runtime')
  await page.getByText('高级系统信息').click()
  await expect(page.getByText(/Version：/)).toBeVisible()
  await expect(page.getByText('PostgreSQL：ok')).toBeVisible()
  await expect(page.getByText('Redis：ok')).toBeVisible()
  await expect(page.getByText(/Worker：/)).toBeVisible()
})

test('failed analysis can be retried from the detail view', async ({ page }) => {
  const marker = e2eMarker('retry')
  await withOwned([marker], async () => {
    await page.goto('/')
    await addInboxText(page, `${marker}\nrecorded fact sentence`)
    await openSourceDetail(page, marker)
    await page.getByRole('button', { name: 'Analyze', exact: true }).click()
    await expect(page.getByText('Summary：结构化摘要')).toBeVisible({ timeout: 20_000 })
    markFailed(marker)
    await page.reload()
    await openSourceDetail(page, marker)
    await expect(page.getByText('Analysis Status：FAILED')).toBeVisible()
    await page.locator('.ant-drawer').getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByText('Summary：结构化摘要')).toBeVisible({ timeout: 20_000 })
  })
})
