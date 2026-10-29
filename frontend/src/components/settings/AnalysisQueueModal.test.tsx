import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalysisQueueModal } from './AnalysisQueueModal'

vi.mock('../../api', () => ({
  fetchAnalysisQueue: vi.fn(),
}))

import { fetchAnalysisQueue } from '../../api'

describe('AnalysisQueueModal', () => {
  beforeEach(() => {
    vi.mocked(fetchAnalysisQueue).mockResolvedValue({
      ok: true,
      summary: { active: 0, pending: 0, running: 0, succeeded: 1, partial: 0, failed: 0 },
      jobs: [{
        run_id: 'fake-run-1',
        source_id: 'source-1',
        source_title: 'Research source',
        status: 'SUCCEEDED',
        stage: 'SUCCEEDED',
        stage_label: '分析完成',
        provider_type: 'FAKE',
        model_name: 'fake-model',
        is_simulated: true,
        error_code: 'WORKER_NOT_CONSUMING',
        error_message: '后台任务长时间未开始',
        can_retry: false,
      }],
    })
  })

  it('labels fake output as simulated and a retained success error as historical', async () => {
    render(<AnalysisQueueModal open onClose={() => undefined} />)

    expect(await screen.findByText('模拟测试 · fake-model')).toBeInTheDocument()
    expect(screen.getByText('历史告警（任务现为SUCCEEDED）：后台任务长时间未开始')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Research source'))
    await waitFor(() => expect(screen.getByText('模拟测试（未调用真实模型） · fake-model')).toBeInTheDocument())
    expect(screen.getByText('后台任务长时间未开始')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新分析' })).not.toBeInTheDocument()
  }, 15000)
})
