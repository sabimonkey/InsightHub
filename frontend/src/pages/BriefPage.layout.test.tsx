import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BriefPage } from './BriefPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('BriefPage stable topic and detail controls', () => {
  it('keeps preset topic order and visible label dimensions when toggled', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/topics') return jsonResponse([
        { id: 'a', name: 'Agent' },
        { id: 'b', name: 'Robotics' },
        { id: 'c', name: 'Finance' },
      ])
      if (url === '/api/categories') return jsonResponse([])
      if (url === '/api/briefs') return jsonResponse({ briefs: [] })
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      return jsonResponse({})
    }))

    render(<BriefPage />)
    const chips = await screen.findAllByRole('button', { name: /^(Agent|Robotics|Finance)$/ })
    const labels = chips.map((chip) => chip.textContent)
    expect(labels).toEqual(['Agent', 'Robotics', 'Finance'])
    const sizes = chips.map((chip) => ({ width: chip.getBoundingClientRect().width, height: chip.getBoundingClientRect().height }))

    await user.click(chips[1])
    expect(chips[1]).toHaveAttribute('aria-pressed', 'true')
    expect(chips[1]).not.toHaveTextContent('×')
    expect(chips.map((chip) => chip.textContent)).toEqual(labels)
    expect(chips.map((chip) => ({ width: chip.getBoundingClientRect().width, height: chip.getBoundingClientRect().height }))).toEqual(sizes)

    await user.click(chips[1])
    expect(chips[1]).toHaveAttribute('aria-pressed', 'false')
    expect(chips.map((chip) => chip.textContent)).toEqual(labels)
  })

  it('uses the horizontal detail selector with the existing STANDARD default and values', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/topics' || url === '/api/categories') return jsonResponse([])
      if (url === '/api/briefs') return jsonResponse({ briefs: [] })
      if (url === '/api/llm/providers') return jsonResponse([{ configured: true }])
      return jsonResponse({})
    }))
    render(<BriefPage />)
    const selector = await screen.findByLabelText('detail level')
    expect(selector).toHaveTextContent('极简')
    expect(selector).toHaveTextContent('标准')
    expect(selector).toHaveTextContent('详细')
    expect(within(selector).getByRole('radio', { name: '标准' })).toBeChecked()
    fireEvent.click(within(selector).getByText('详细'))
    await waitFor(() => expect(within(selector).getByRole('radio', { name: '详细' })).toBeChecked())
  })
})
