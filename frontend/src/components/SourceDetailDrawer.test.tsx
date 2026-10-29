import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalysisView, SourceDetail } from '../types'
import { SourceDetailDrawer } from './SourceDetailDrawer'

afterEach(cleanup)

describe('SourceDetailDrawer retry', () => {
  it('retries a failed analysis without hiding the failure', async () => {
    const onAnalyze = vi.fn()
    render(
      <SourceDetailDrawer
        open
        detail={{ source: { id: 'src-1', display_name: 'note', source_type: 'TEXT', status: 'STORED', privacy_level: 'PRIVATE' }, ingestions: [] } as SourceDetail}
        discovery={null}
        analysis={{ run: { id: 'run-1', status: 'FAILED', provider_type: 'FAKE', model_name: 'fake', prompt_name: 'analysis', prompt_version: '1', error_code: 'WORKER_INTERRUPTED' }, providers_configured: true } as AnalysisView}
        onClose={() => undefined}
        onAnalyze={onAnalyze}
      />,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onAnalyze).toHaveBeenCalledWith('src-1')
    expect(screen.getByText(/WORKER_INTERRUPTED|FAILED|失败/)).toBeTruthy()
  })
})
