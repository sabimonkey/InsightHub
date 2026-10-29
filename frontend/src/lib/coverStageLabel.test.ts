import { describe, expect, it } from 'vitest'
import { coverStageLabel } from './coverStageLabel'

describe('coverStageLabel', () => {
  it('maps known stages', () => {
    expect(coverStageLabel('QUEUED', 'QUEUED')).toContain('队列')
    expect(coverStageLabel('GENERATING', 'GENERATING')).toContain('MiniMax')
    expect(coverStageLabel('SUCCEEDED', 'SUCCEEDED')).toBe('生成成功')
    expect(coverStageLabel('FAILED', 'FAILED')).toBe('生成失败')
  })
})
