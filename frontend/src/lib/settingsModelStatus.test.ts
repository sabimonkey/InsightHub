import { describe, expect, it } from 'vitest'
import {
  assignedWorkflowLabels,
  effectiveRouteReady,
  providerCredentialLabel,
  credentialSourceLabel,
  routeConflictDisabled,
  showCoverImageRole,
} from './settingsModelStatus'
import type { LlmDeployment, LlmProvider } from '../types'

const workflowNameByKey = {
  ANALYSIS: '资料分析',
  ASK_PLANNER: '问答规划',
  ASK_ANSWER: '问答回答',
  BRIEF: '笔记生成',
}

describe('settingsModelStatus', () => {
  it('shows only assigned workflow labels', () => {
    const labels = assignedWorkflowLabels(
      { ANALYSIS: 'dep-a', ASK_ANSWER: 'dep-b', BRIEF: 'dep-a' },
      'dep-a',
      workflowNameByKey,
    )
    expect(labels).toEqual(['资料分析', '笔记生成'])
  })

  it('marks route not ready when deployment disabled', () => {
    const dep = { enabled: false, route_ready: true } as LlmDeployment
    expect(effectiveRouteReady(dep)).toBe(false)
  })

  it('shows minimax cover role only when configured and enabled', () => {
    const provider = {
      provider_type: 'MINIMAX_IMAGE',
      configured: false,
      enabled: true,
    } as LlmProvider
    const dep = { enabled: true, capabilities: { supports_image_generation: true } } as LlmDeployment
    expect(showCoverImageRole(provider, dep)).toBe(false)
    provider.configured = true
    expect(showCoverImageRole(provider, dep)).toBe(true)
  })

  it('flags disabled deployment still referenced by routes', () => {
    expect(routeConflictDisabled({ enabled: false } as LlmDeployment, ['资料分析'])).toBe(true)
    expect(routeConflictDisabled({ enabled: true } as LlmDeployment, ['资料分析'])).toBe(false)
  })

  it('labels fake provider as simulation', () => {
    const label = providerCredentialLabel({ provider_type: 'FAKE', configured: true, is_local: false } as LlmProvider)
    expect(label.label).toBe('模拟测试')
  })

  it('maps credential source labels', () => {
    expect(credentialSourceLabel('vault')).toBe('页面安全存储')
    expect(credentialSourceLabel('environment')).toBe('环境变量')
    expect(credentialSourceLabel('none')).toBe('未配置')
  })
})
