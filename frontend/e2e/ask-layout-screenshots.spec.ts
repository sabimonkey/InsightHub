import { expect, test } from '@playwright/test'
import { nav } from './resources'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

const OUT = path.join(os.tmpdir(), `insighthub-e2e-${process.pid}`, 'ask-ux-r3')

test.beforeAll(() => {
  fs.mkdirSync(OUT, { recursive: true })
})

const OUT_R3 = OUT
const OUT_FB = path.join(os.tmpdir(), `insighthub-e2e-${process.pid}`, 'm-user-feedback-r1')

for (const viewport of [
  { name: '1920', width: 1920, height: 1080 },
  { name: '1566', width: 1566, height: 673 },
  { name: '1448', width: 1448, height: 701 },
  { name: '1366', width: 1366, height: 768 },
  { name: '1024', width: 1024, height: 768 },
  { name: '390', width: 390, height: 844 },
]) {
  test(`ask layout capture ${viewport.name}`, async ({ page }) => {
    await page.request.post('/api/ask/sessions/clear')
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto('/')
    await nav(page, '问答').click()
    await expect(page.getByRole('textbox', { name: '输入问题' })).toBeVisible()
    const shotDir = ['1566', '1448'].includes(viewport.name) ? OUT_FB : OUT_R3
    fs.mkdirSync(shotDir, { recursive: true })
    await page.screenshot({ path: path.join(shotDir, `ask-empty-${viewport.name}.png`), fullPage: false })
  })
}
