import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProviderSettingsCard } from './ProviderSettingsCard'

vi.mock('./CoverPromptEditor', () => ({ CoverPromptEditor: () => null }))
vi.mock('./CoverQueueModal', () => ({ CoverQueueModal: () => null }))
vi.mock('./ProviderApiKeyModal', () => ({ ProviderApiKeyActions: () => null }))
vi.mock('./SettingsStatusChip', () => ({ SettingsStatusChip: ({ label }: { label: string }) => <span>{label}</span> }))
vi.mock('./AnalysisBackfillModal', () => ({ AnalysisBackfillModal: () => null }))
vi.mock('./AnalysisQueueModal', () => ({ AnalysisQueueModal: () => null }))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const provider = {
  id: 'minimax-provider',
  name: 'MiniMax',
  provider_type: 'MINIMAX_IMAGE',
  base_url: 'https://api.minimax.cn',
  model: 'image-01',
  is_local: false,
  configured: true,
  enabled: true,
  is_default: false,
  api_key_state: 'CONFIGURED',
  deployments: [],
} as const

function renderCard() {
  return render(
    <ProviderSettingsCard
      provider={provider}
      routes={{}}
      workflowNameByKey={{}}
      statusByDeployment={{}}
      onAddModel={() => undefined}
      onToggleProvider={() => undefined}
      onRetireProvider={() => undefined}
      onEditDeployment={() => undefined}
      onToggleDeployment={() => undefined}
      onTestDeployment={() => undefined}
      onDeleteDeployment={() => undefined}
      onConfigureApiKey={() => undefined}
      onClearApiKey={() => undefined}
    />,
  )
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('MiniMax local cover safety cap', () => {
  it('saves 200, uses the server response, and reads it again after remount', async () => {
    const user = userEvent.setup()
    let persisted = 100
    const requests: Array<{ method: string; body?: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) as unknown : undefined
      requests.push({ method, body })
      if (method === 'PATCH') {
        persisted = (body as { monthly_budget: number }).monthly_budget
        return jsonResponse({ ok: true, monthly_budget: persisted, budget_range: { min: 1, max: 500 } })
      }
      return jsonResponse({ ok: true, auto_enabled: true, monthly_budget: persisted, budget_range: { min: 1, max: 500 } })
    }))

    const first = renderCard()
    const input = await screen.findByRole('spinbutton', { name: 'InsightHub 本地安全上限' })
    await waitFor(() => expect(input).toHaveAttribute('aria-valuenow', '100'))
    await user.clear(input)
    await user.type(input, '200')
    expect(input).toHaveValue('200')
    await user.click(screen.getByRole('button', { name: '保存安全上限' }))
    await screen.findByText('InsightHub 本地安全上限已保存：200 次尝试/月')
    expect(requests.find((request) => request.method === 'PATCH')?.body).toEqual({ monthly_budget: 200 })
    expect(input).toHaveAttribute('aria-valuenow', '200')

    first.unmount()
    renderCard()
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'InsightHub 本地安全上限' })).toHaveAttribute('aria-valuenow', '200'))
  })

  it('shows server validation errors and does not announce a false save', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH') return jsonResponse({ detail: '本地安全上限必须在 1 至 500 次尝试/月之间。' }, 422)
      return jsonResponse({ ok: true, auto_enabled: false, monthly_budget: 100, budget_range: { min: 1, max: 500 } })
    }))
    renderCard()
    const input = await screen.findByRole('spinbutton', { name: 'InsightHub 本地安全上限' })
    await user.clear(input)
    await user.type(input, '200')
    fireEvent.click(screen.getByRole('button', { name: '保存安全上限' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert')).toHaveTextContent('本地安全上限必须在 1 至 500 次尝试/月之间。')
    expect(screen.queryByText('InsightHub 本地安全上限已保存：200 次尝试/月')).not.toBeInTheDocument()
    expect(input).toHaveValue('200')
  })
})
