import type { LlmDeployment, LlmProvider } from '../types'

const WORKFLOW_KEYS = ['EXTRACTION_AI', 'ANALYSIS', 'ASK_PLANNER', 'ASK_ANSWER', 'BRIEF'] as const

export function assignedWorkflowLabels(
  routes: Record<string, string>,
  deploymentId: string,
  workflowNameByKey: Record<string, string>,
): string[] {
  return Object.entries(routes)
    .filter(([workflow, id]) => WORKFLOW_KEYS.includes(workflow as (typeof WORKFLOW_KEYS)[number]) && id === deploymentId)
    .map(([workflow]) => workflowNameByKey[workflow] ?? workflow)
}

export function effectiveRouteReady(deployment: LlmDeployment): boolean {
  return deployment.enabled && deployment.route_ready
}

export function routeReadyLabel(deployment: LlmDeployment): string {
  if (!deployment.enabled) return '暂不可用于路由'
  return deployment.route_ready ? '路由就绪' : '暂不可用于路由'
}

export function providerKindSubtitle(provider: LlmProvider): string {
  if (provider.provider_type === 'MINIMAX_IMAGE') return '云端图像生成服务'
  if (provider.provider_type === 'ZAI') return `官方 GLM API · ${provider.base_url}`
  if (provider.provider_type === 'FAKE') return '自动化测试模拟（不调用真实 API）'
  if (provider.is_local) return '本地 OpenAI 兼容服务'
  return '云端语言模型服务'
}

export function credentialSourceLabel(source: string | undefined): string {
  if (source === 'vault') return '页面安全存储'
  if (source === 'environment') return '环境变量'
  return '未配置'
}

export function providerCredentialLabel(provider: LlmProvider): { label: string; variant: 'success' | 'warning' | 'muted' } {
  if (provider.provider_type === 'FAKE') {
    return { label: '模拟测试', variant: 'warning' }
  }
  if (provider.is_local) {
    return { label: provider.configured ? '本地' : '未配置', variant: provider.configured ? 'success' : 'warning' }
  }
  return provider.configured
    ? { label: '已配置', variant: 'success' }
    : { label: '未配置', variant: 'warning' }
}

export function showCoverImageRole(provider: LlmProvider, deployment: LlmDeployment): boolean {
  return (
    provider.provider_type === 'MINIMAX_IMAGE' &&
    deployment.enabled &&
    provider.configured &&
    Boolean(deployment.capabilities?.supports_image_generation)
  )
}

export function routeConflictDisabled(deployment: LlmDeployment, workflowLabels: string[]): boolean {
  return !deployment.enabled && workflowLabels.length > 0
}
