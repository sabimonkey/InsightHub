import { expect, test } from '@playwright/test'
import { nav } from './resources'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

const OUT = path.join(os.tmpdir(), `insighthub-e2e-${process.pid}`, 'm-ux-r2')

test.describe('M-UX-R2 visual capture', () => {
  test.beforeAll(() => {
    fs.mkdirSync(OUT, { recursive: true })
  })

  for (const viewport of [
    { name: '1920', width: 1920, height: 1080 },
    { name: '1366', width: 1366, height: 768 },
    { name: '390', width: 390, height: 844 },
  ]) {
    test(`capture core pages ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto('/')
      await nav(page, '知识库').click()
      await expect(page.getByTestId('knowledge-grid')).toBeVisible()
      await page.screenshot({ path: path.join(OUT, `library-${viewport.name}.png`), fullPage: true })
      await nav(page, '问答').click()
      await expect(page.getByText('基于你的知识库提问')).toBeVisible()
      await page.screenshot({ path: path.join(OUT, `ask-empty-${viewport.name}.png`), fullPage: true })
      await nav(page, '笔记').click()
      await expect(page.getByText('时间范围')).toBeVisible()
      await page.screenshot({ path: path.join(OUT, `brief-${viewport.name}.png`), fullPage: true })
    })
  }
})
