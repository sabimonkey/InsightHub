import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnalysisProgress } from './AnalysisProgress'

describe('AnalysisProgress', () => {
  it('highlights current stage', () => {
    render(<AnalysisProgress stage="CALLING_MODEL" stageLabel="正在使用 AI 分析资料" />)
    expect(screen.getByText('AI 分析')).toBeInTheDocument()
    expect(screen.getByText('正在使用 AI 分析资料')).toBeInTheDocument()
  })
})
