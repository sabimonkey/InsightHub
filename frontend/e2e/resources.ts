import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { expect, type Page } from '@playwright/test'

export const python = process.env.INSIGHTHUB_PYTHON ?? resolve(
  '..',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
export const backend = resolve('..', 'backend')

export function e2eMarker(name: string) {
  return `e2e-${name}-${crypto.randomUUID()}`
}

export function purgeOwned(markers: string[], topics: string[] = []) {
  const args = [`${backend}\\tests\\e2e_cleanup.py`, ...markers]
  for (const topic of topics) {
    args.push('--topic', topic)
  }
  execFileSync(python, args, { cwd: backend, stdio: 'inherit' })
}

export async function withOwned(markers: string[], body: () => Promise<void>, topics: string[] = []) {
  let failed = false
  try {
    await body()
  } catch (error) {
    failed = true
    throw error
  } finally {
    try {
      purgeOwned(markers, topics)
    } catch (cleanupError) {
      console.error(cleanupError)
      if (!failed) {
        throw cleanupError
      }
    }
  }
}

export async function addInboxText(page: Page, text: string) {
  const pending = page.waitForResponse(
    (response) => response.url().includes('/api/ingest/text') && response.request().method() === 'POST',
  )
  await page.getByRole('tab', { name: '文本' }).click()
  await page.getByRole('textbox', { name: '文本' }).fill(text)
  await page.getByRole('button', { name: /添\s*加/ }).click()
  const response = await pending
  expect(response.ok()).toBeTruthy()
  await expect(page.getByText(/资料已保存/)).toBeVisible()
}

export async function openLibraryForMarker(page: Page, marker: string) {
  const sourceId = await findInboxSourceId(page, marker)
  await page.goto(`/?view=library&source=${sourceId}`)
  const card = page.locator(`[data-source-id="${sourceId}"]`)
  await expect(card).toBeVisible({ timeout: 20_000 })
  return card
}

export async function openResearchNote(page: Page, marker: string) {
  const card = await openLibraryForMarker(page, marker)
  await card.click()
}

export async function openSourceDetail(page: Page, marker: string) {
  const card = await openLibraryForMarker(page, marker)
  await card.getByRole('button', { name: '更多操作' }).click()
  await page.getByRole('menuitem', { name: '详情' }).click()
  await expect(page.getByText('提取内容')).toBeVisible()
}

export async function findInboxSourceId(page: Page, marker: string): Promise<string> {
  const inbox = await page.request.get('/api/inbox?filter=all&page=1&page_size=50')
  const items = ((await inbox.json()) as { items: Array<{ source_id: string; display_name: string; title?: string }> }).items
  const item = items.find((row) => row.display_name === marker || row.display_name?.startsWith(marker) || row.title?.includes(marker))
  if (!item?.source_id) {
    throw new Error(`inbox source not found for marker ${marker}`)
  }
  return item.source_id
}

export function nav(page: Page, label: '收集' | '知识库' | '搜索' | '问答' | '笔记' | '设置') {
  return page.getByRole('button', { name: label, exact: true })
}
