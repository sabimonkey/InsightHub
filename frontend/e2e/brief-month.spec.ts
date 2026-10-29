import { expect, test } from '@playwright/test'
import { resolvePreset } from '../src/dates'
import { nav } from './resources'

test.describe('brief month preset', () => {
  test('this month uses first day through today', async ({ page }) => {
    await page.addInitScript(() => {
      const fixed = new Date('2026-10-20T12:00:00')
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ;(globalThis as any).Date = class extends Date {
        constructor(...args: ConstructorParameters<typeof Date>) {
          if (args.length === 0) super(fixed.getTime())
          else super(...args)
        }
        static now() {
          return fixed.getTime()
        }
      }
    })
    const expected = resolvePreset('thisMonth', new Date('2026-10-20'))
    await page.goto('/')
    await nav(page, '笔记').click()
    await page.getByRole('button', { name: 'preset this month' }).click()
    await expect(page.getByLabel('brief start')).toHaveValue(expected.start)
    await expect(page.getByLabel('brief end')).toHaveValue(expected.end)
  })
})
