import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CoverPromptEditor } from './CoverPromptEditor'

const api = vi.hoisted(() => ({
  fetchGlobalCoverPrompt: vi.fn(), fetchLibrary: vi.fn(), previewGlobalCoverPrompt: vi.fn(),
  saveGlobalCoverPrompt: vi.fn(), resetGlobalCoverPrompt: vi.fn(),
}))
vi.mock('../../api', () => api)

const config = {
  ok: true, prompt: 'Global style', revision: 3, version: 'global-cover-r1',
  updated_at: '2026-10-27T00:00:00Z', max_global_prompt_chars: 800, system_default_prompt: 'System default',
}

describe('CoverPromptEditor', () => {
  beforeEach(() => {
    api.fetchGlobalCoverPrompt.mockReset().mockResolvedValue(config)
    api.fetchLibrary.mockReset().mockResolvedValue({ items: [{ source_id: 'source-1', display_name: 'Robotics notes' }] })
    api.previewGlobalCoverPrompt.mockReset().mockResolvedValue({
      ok: true, title: 'Robotics notes', topic: 'robotics', palette_direction: 'cool',
      prompt: 'Global style\n\nArticle topic and visual subject: robotics.', prompt_char_count: 58,
      prompt_revision: 3, prompt_version: 'global-cover-r1',
    })
    api.saveGlobalCoverPrompt.mockReset()
    api.resetGlobalCoverPrompt.mockReset()
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('reads the persisted prompt only when the foldout opens and previews through the backend', async () => {
    const user = userEvent.setup()
    render(<CoverPromptEditor />)
    expect(api.fetchGlobalCoverPrompt).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('全局配图 Prompt'))
    await waitFor(() => expect(api.fetchGlobalCoverPrompt).toHaveBeenCalledTimes(1))
    expect(await screen.findByDisplayValue('Global style')).toBeTruthy()
    expect(api.fetchLibrary).toHaveBeenCalledWith({ scope: 'mine' })

    fireEvent.change(screen.getByLabelText('全局配图 Prompt'), { target: { value: 'Edited global style' } })
    expect(screen.getByText('有未保存修改')).toBeTruthy()
    await user.click(screen.getByRole('combobox', { name: '预览资料' }))
    await user.click(await screen.findByText('Robotics notes'))
    fireEvent.click(screen.getByRole('button', { name: '预览最终 Prompt' }))
    await waitFor(() => expect(api.previewGlobalCoverPrompt).toHaveBeenCalledWith(expect.objectContaining({
      source_id: 'source-1', global_prompt: 'Edited global style', color_scheme: 'auto',
    })))
    expect(await screen.findByDisplayValue(/Article topic and visual subject/)).toBeTruthy()
  })

  it('persists edits without invoking any generation API', async () => {
    api.saveGlobalCoverPrompt.mockResolvedValue({ ...config, ok: true, prompt: 'Changed', revision: 4 })
    render(<CoverPromptEditor />)
    fireEvent.click(screen.getByText('全局配图 Prompt'))
    await screen.findByDisplayValue('Global style')
    fireEvent.change(screen.getByLabelText('全局配图 Prompt'), { target: { value: 'Changed' } })
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }))
    await waitFor(() => expect(api.saveGlobalCoverPrompt).toHaveBeenCalledWith('Changed'))
    expect(api.previewGlobalCoverPrompt).not.toHaveBeenCalled()
  })
})
