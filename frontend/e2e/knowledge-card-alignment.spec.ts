import { expect, test } from '@playwright/test'
import { addInboxText, e2eMarker, nav, withOwned } from './resources'

test.describe('knowledge card action alignment', () => {
  for (const size of [
    { width: 1920, height: 1080 },
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    test(`more buttons align at ${size.width}px`, async ({ page }) => {
      await page.setViewportSize(size)
      const markers = [e2eMarker('align-a'), e2eMarker('align-b'), e2eMarker('align-c')]
      await withOwned(markers, async () => {
        await page.goto('/')
        await addInboxText(page, `${markers[0]}\nshort`)
        await addInboxText(page, `${markers[1]}\n${'long title '.repeat(12)}`)
        await addInboxText(page, `${markers[2]}\nmedium length title for card`)
        await nav(page, '知识库').click()
        const grid = page.getByTestId('knowledge-grid')
        const cards = markers.map((marker) => grid.locator('.knowledge-card').filter({ hasText: marker.slice(0, 14) }))
        const buttons = cards.map((card) => card.getByRole('button', { name: '更多操作' }))
        await expect(buttons[0]).toBeVisible({ timeout: 20_000 })
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width)
        const geometry = await Promise.all(cards.map(async (card) => {
          await expect(card).toBeVisible()
          return card.evaluate((element) => {
            const body = element.querySelector<HTMLElement>('.knowledge-card-body')!
            const title = element.querySelector<HTMLElement>('.knowledge-card-title')!
            const status = element.querySelector<HTMLElement>('.knowledge-card-status')!
            const button = element.querySelector<HTMLElement>('.knowledge-card-actions button[aria-label="更多操作"]')!
            const cardRect = element.getBoundingClientRect()
            const bodyRect = body.getBoundingClientRect()
            const titleRect = title.getBoundingClientRect()
            const statusRect = status.getBoundingClientRect()
            const buttonRect = button.getBoundingClientRect()
            const style = getComputedStyle(body)
            return {
              cardTop: cardRect.top,
              bodyRight: bodyRect.right,
              bodyBottom: bodyRect.bottom,
              paddingRight: parseFloat(style.paddingRight),
              paddingBottom: parseFloat(style.paddingBottom),
              titleBottom: titleRect.bottom,
              statusBottom: statusRect.bottom,
              buttonTop: buttonRect.top,
              buttonRight: buttonRect.right,
              buttonBottom: buttonRect.bottom,
              buttonPosition: getComputedStyle(button).position,
              hasCoverImage: Boolean(element.querySelector('.knowledge-card-image')),
              cardRight: cardRect.right,
            }
          })
        }))
        for (const item of geometry) {
          expect(item.buttonPosition).not.toBe('absolute')
          expect(Math.abs(item.buttonRight - (item.bodyRight - item.paddingRight))).toBeLessThanOrEqual(2)
          expect(Math.abs(item.buttonBottom - (item.bodyBottom - item.paddingBottom))).toBeLessThanOrEqual(2)
          expect(item.buttonTop).toBeGreaterThanOrEqual(item.statusBottom - 1)
          expect(item.hasCoverImage).toBe(false)
          expect(item.buttonRight).toBeLessThanOrEqual(item.cardRight)
        }
        const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length)
        if (columns > 1) {
          const rows = new Map<number, number[]>()
          geometry.forEach((item, index) => {
            const key = Math.round(item.cardTop)
            rows.set(key, [...(rows.get(key) ?? []), index])
          })
          for (const indexes of rows.values()) {
            if (indexes.length < 2) continue
            const bottoms = indexes.map((index) => geometry[index].buttonBottom)
            expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThanOrEqual(2)
          }
        }
        await buttons[0].click()
        await expect(page.getByRole('menuitem', { name: '查看详情' })).toBeVisible()
        await page.keyboard.press('Escape')
      })
    })
  }
})
