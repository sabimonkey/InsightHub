import { expect, test } from '@playwright/test'

test.describe('knowledge cover rendering', () => {
  test('themed cover when library has no preview url', async ({ page }) => {
    await page.route('**/api/library**', async (route) => {
      await route.fulfill({
        json: {
          items: [
            {
              source_id: '11111111-1111-1111-1111-111111111111',
              display_name: 'Cover themed',
              title: 'Cover themed',
              source_type: 'TEXT',
              categories: ['knowledge'],
              last_collected_at: '2026-10-01T00:00:00Z',
              preview_image_url: null,
              cover_status: 'NO_IMAGE_IN_SOURCE',
            },
          ],
        },
      })
    })
    await page.goto('/?view=library')
    await expect(page.getByTestId('knowledge-themed-cover').first()).toBeVisible()
  })

  test('real cover img when preview url present', async ({ page }) => {
    await page.route('**/api/library**', async (route) => {
      await route.fulfill({
        json: {
          items: [
            {
              source_id: '22222222-2222-2222-2222-222222222222',
              display_name: 'Cover photo',
              title: 'Cover photo',
              source_type: 'URL',
              categories: [],
              last_collected_at: '2026-10-01T00:00:00Z',
              preview_image_url: '/api/sources/22222222-2222-2222-2222-222222222222/cover-image',
              cover_status: 'HAS_PREVIEW',
            },
          ],
        },
      })
    })
    await page.route('**/cover-image', async (route) => {
      const png = Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
        'base64',
      )
      await route.fulfill({ body: png, contentType: 'image/png' })
    })
    await page.goto('/?view=library')
    await expect(page.locator('.knowledge-cover--photo img').first()).toBeVisible()
  })
})
