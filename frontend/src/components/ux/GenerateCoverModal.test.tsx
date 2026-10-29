import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GenerateCoverModal } from './GenerateCoverModal'

const api = vi.hoisted(() => ({
  fetchCoverPrompt: vi.fn(),
  fetchCoverStatus: vi.fn(),
  reviewCoverCandidate: vi.fn(),
  startCoverGenerate: vi.fn(),
}))

vi.mock('../../api', () => api)

const idleStatus = {
  ok: true,
  lifecycle: 'idle' as const,
  current_cover_url: '/api/sources/source-1/cover-image?v=old-asset',
  cover_url: '/api/sources/source-1/cover-image?v=old-asset',
}

const candidateStatus = {
  ok: true,
  run_id: 'run-1',
  status: 'SUCCEEDED',
  stage: 'SUCCEEDED',
  lifecycle: 'succeeded' as const,
  terminal_success: true,
  current_cover_url: '/api/sources/source-1/cover-image?v=old-asset',
  candidate_asset_id: 'candidate-1',
  candidate_cover_url: '/api/sources/source-1/cover-image?asset_id=candidate-1',
  candidate_is_current: false,
  candidate_review_state: null,
}

function renderModal(onClose = vi.fn(), onDone = vi.fn()) {
  render(<GenerateCoverModal sourceId="source-1" title="研究资料" open onClose={onClose} onDone={onDone} />)
  return { onClose, onDone }
}

describe('GenerateCoverModal', () => {
  beforeEach(() => {
    api.fetchCoverPrompt.mockReset()
    api.fetchCoverStatus.mockReset()
    api.reviewCoverCandidate.mockReset()
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('request-1').mockReturnValueOnce('request-2') })
    api.fetchCoverPrompt.mockResolvedValue({
      ok: true,
      prompt: 'A cool, high contrast research cover',
      max_prompt_chars: 1500,
      content_usable: true,
      provider: 'MiniMax',
      model: 'image-01',
      budget_used: 54,
      monthly_budget: 100,
      budget_available: true,
      current_cover_url: idleStatus.current_cover_url,
      prompt_revision: 1,
      prompt_preview_token: 'a'.repeat(64),
    })
    api.fetchCoverStatus.mockResolvedValue(idleStatus)
    api.reviewCoverCandidate.mockResolvedValue({ ok: true })
    api.startCoverGenerate.mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('opening only reads status and shows an explicit confirmation with the current cover', async () => {
    renderModal()

    await waitFor(() => expect(api.fetchCoverPrompt).toHaveBeenCalledTimes(1), { timeout: 10000 })
    expect(await screen.findByRole('button', { name: '确认重新生成' }, { timeout: 10000 })).toBeTruthy()
    expect(screen.getByRole('img', { name: '当前封面' }).getAttribute('src')).toContain('old-asset')
    expect(screen.getByText(/54\/100 次生成尝试/)).toBeTruthy()
    expect(screen.getByText(/不是 MiniMax 官方套餐剩余额度/)).toBeTruthy()
    expect(api.startCoverGenerate).not.toHaveBeenCalled()
  })

  it('does not present a historical applied success as a new result', async () => {
    api.fetchCoverStatus.mockResolvedValue({ ...candidateStatus, candidate_is_current: true, candidate_review_state: 'APPLIED' })
    renderModal()
    expect(await screen.findByRole('button', { name: '确认重新生成' })).toBeTruthy()
    expect(screen.queryByRole('img', { name: '候选封面' })).toBeNull()
    expect(api.startCoverGenerate).not.toHaveBeenCalled()
  })

  it('reuses the request key after an uncertain network failure', async () => {
    const user = userEvent.setup()
    api.startCoverGenerate.mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce(candidateStatus)
    renderModal()
    await user.click(await screen.findByRole('button', { name: '确认重新生成' }))
    await user.click(await screen.findByRole('button', { name: '确认重试生成' }))
    await screen.findByRole('img', { name: '候选封面' })
    expect(api.startCoverGenerate.mock.calls.map((call) => call[1].idempotency_key)).toEqual(['request-1', 'request-1'])
  })

  it('recovers an unreviewed candidate on reopen without generating again', async () => {
    api.fetchCoverStatus.mockResolvedValue(candidateStatus)
    renderModal()
    expect(await screen.findByRole('img', { name: '候选封面' })).toBeTruthy()
    expect(api.startCoverGenerate).not.toHaveBeenCalled()
  })

  it('confirms once, previews both assets, and records keep-old without applying the candidate', async () => {
    const user = userEvent.setup()
    const { onClose, onDone } = renderModal()
    api.startCoverGenerate.mockResolvedValue(candidateStatus)

    await user.click(await screen.findByRole('button', { name: '确认重新生成' }))
    expect(api.startCoverGenerate).toHaveBeenCalledTimes(1)
    expect(api.startCoverGenerate.mock.calls[0][1]).toMatchObject({ confirm_send: true, idempotency_key: 'request-1' })
    expect(await screen.findByRole('img', { name: '候选封面' })).toBeTruthy()
    fireEvent.load(screen.getByRole('img', { name: '候选封面' }))
    expect(screen.getByRole('button', { name: '使用新图' }).hasAttribute('disabled')).toBe(false)

    await user.click(screen.getByRole('button', { name: '保留旧图' }))
    await waitFor(() => expect(api.reviewCoverCandidate).toHaveBeenCalledWith('run-1', 'keep_old'))
    expect(api.reviewCoverCandidate).not.toHaveBeenCalledWith('run-1', 'use_new')
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('applies the candidate only after the user chooses use-new', async () => {
    const user = userEvent.setup()
    const { onDone } = renderModal()
    api.startCoverGenerate.mockResolvedValue(candidateStatus)

    await user.click(await screen.findByRole('button', { name: '确认重新生成' }))
    await screen.findByRole('img', { name: '候选封面' })
    fireEvent.load(screen.getByRole('img', { name: '候选封面' }))
    await user.click(screen.getByRole('button', { name: '使用新图' }))

    await waitFor(() => expect(api.reviewCoverCandidate).toHaveBeenCalledWith('run-1', 'use_new'))
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
  })

  it('does not submit duplicate requests while the confirmed request is pending', async () => {
    const user = userEvent.setup()
    renderModal()
    let resolveRequest: ((value: typeof candidateStatus) => void) | undefined
    api.startCoverGenerate.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))

    const confirm = await screen.findByRole('button', { name: '确认重新生成' })
    await user.click(confirm)
    await user.click(confirm)
    expect(api.startCoverGenerate).toHaveBeenCalledTimes(1)
    resolveRequest?.(candidateStatus)
    await screen.findByRole('img', { name: '候选封面' })
  })

  it('requires a second confirmation and sends a distinct idempotency key for another image', async () => {
    const user = userEvent.setup()
    api.fetchCoverPrompt
      .mockResolvedValueOnce({
        ok: true,
        prompt: 'Initial prompt',
        prompt_revision: 1,
        prompt_preview_token: 'a'.repeat(64),
        budget_used: 54,
        monthly_budget: 100,
        budget_available: true,
        content_usable: true,
      })
      .mockResolvedValueOnce({
        ok: true,
        prompt: 'Initial prompt after first generation',
        prompt_revision: 1,
        prompt_preview_token: 'a'.repeat(64),
        budget_used: 55,
        monthly_budget: 100,
        budget_available: true,
        content_usable: true,
      })
      .mockResolvedValueOnce({
        ok: true,
        prompt: 'Prompt refreshed for recent palette history',
        prompt_revision: 1,
        prompt_preview_token: 'b'.repeat(64),
        budget_used: 55,
        monthly_budget: 100,
        budget_available: true,
        content_usable: true,
      })
    renderModal()
    api.startCoverGenerate.mockResolvedValueOnce(candidateStatus).mockResolvedValueOnce({
      ok: true,
      run_id: 'run-2',
      status: 'QUEUED',
      stage: 'QUEUED',
      lifecycle: 'running',
      current_cover_url: idleStatus.current_cover_url,
    })

    await user.click(await screen.findByRole('button', { name: '确认重新生成' }))
    await screen.findByRole('img', { name: '候选封面' })
    await user.click(screen.getByRole('button', { name: '再生成一张' }))
    expect(await screen.findByRole('button', { name: '确认并再次生成' })).toBeTruthy()
    await waitFor(() => expect(api.fetchCoverPrompt).toHaveBeenCalledTimes(3))
    expect(api.startCoverGenerate).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: '确认并再次生成' }))
    await waitFor(() => expect(api.startCoverGenerate).toHaveBeenCalledTimes(2))
    expect(api.startCoverGenerate.mock.calls.map((call) => call[1].idempotency_key)).toEqual(['request-1', 'request-2'])
    expect(api.startCoverGenerate.mock.calls[1][1].prompt_preview_token).toBe('b'.repeat(64))
  })

  it('leaves the current preview in place and does not apply when generation fails', async () => {
    const user = userEvent.setup()
    renderModal()
    api.startCoverGenerate.mockResolvedValue({ ok: false, code: 'MINIMAX_ERROR', message: '生成失败' })

    await user.click(await screen.findByRole('button', { name: '确认重新生成' }))

    expect(await screen.findByText('生成失败')).toBeTruthy()
    expect(screen.getByRole('img', { name: '当前封面' }).getAttribute('src')).toContain('old-asset')
    expect(screen.queryByRole('img', { name: '候选封面' })).toBeNull()
    expect(api.reviewCoverCandidate).not.toHaveBeenCalled()
  })
})
