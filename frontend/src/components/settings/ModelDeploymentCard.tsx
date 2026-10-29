import { Button, Collapse } from 'antd'
import type { LlmDeployment, LlmProvider } from '../../types'
import {
  assignedWorkflowLabels,
  effectiveRouteReady,
  routeConflictDisabled,
  routeReadyLabel,
  showCoverImageRole,
} from '../../lib/settingsModelStatus'
import { SettingsStatusChip } from './SettingsStatusChip'

type Props = {
  deployment: LlmDeployment
  provider: LlmProvider
  routes: Record<string, string>
  workflowNameByKey: Record<string, string>
  probeSummary?: string
  onEdit: () => void
  onToggleEnabled: () => void
  onTest: () => void
  onDelete?: () => void
}

function capLabel(caps: Record<string, unknown> | undefined, key: string) {
  return caps?.[key] === true ? '支持' : '不支持'
}

function verified(caps: Record<string, unknown> | undefined, probe: string) {
  const value = caps?.[`verified_${probe}`]
  return value ? String(value) : '未探测'
}

export function ModelDeploymentCard({
  deployment,
  provider,
  routes,
  workflowNameByKey,
  probeSummary,
  onEdit,
  onToggleEnabled,
  onTest,
  onDelete,
}: Props) {
  const caps = deployment.capabilities ?? {}
  const imageGeneration = provider.provider_type === 'MINIMAX_IMAGE' || caps.supports_image_generation === true
  const workflowLabels = assignedWorkflowLabels(routes, deployment.id, workflowNameByKey)
  const routeReady = effectiveRouteReady(deployment)
  const title = deployment.model_id || deployment.display_name
  const showDisplayAlias = deployment.display_name && deployment.display_name !== deployment.model_id

  return (
    <article className="model-deployment-row" aria-label={`model ${deployment.display_name}`}>
      <div className="model-deployment-row-main">
        <div className="model-deployment-row-info">
          <div className="model-deployment-row-titleline">
            <strong className="model-deployment-row-name">{title}</strong>
            <div className="model-deployment-row-status">
              <SettingsStatusChip
                label={deployment.enabled ? '已启用' : '已禁用'}
                variant={deployment.enabled ? 'success' : 'muted'}
              />
              {!imageGeneration ? (
                <SettingsStatusChip
                  label={routeReadyLabel(deployment)}
                  variant={routeReady ? 'accent' : 'warning'}
                  title={routeReady ? '凭证与 Provider 状态满足路由条件' : '未启用、未配置或 Provider 不可用'}
                />
              ) : null}
              {showCoverImageRole(provider, deployment) ? (
                <SettingsStatusChip label="封面生图" variant="accent" />
              ) : null}
              {workflowLabels.map((label) => (
                <SettingsStatusChip key={label} label={label} variant="neutral" />
              ))}
              {routeConflictDisabled(deployment, workflowLabels) ? (
                <SettingsStatusChip label="路由占用·已禁用" variant="danger" />
              ) : null}
            </div>
          </div>
          {showDisplayAlias ? <span className="model-deployment-row-alias">{deployment.display_name}</span> : null}
          <Collapse
            size="small"
            bordered={false}
            className="model-deployment-tech"
            items={[
              {
                key: 'tech',
                label: '能力与技术详情',
                children: (
                  <div className="model-deployment-tech-body">
                    {imageGeneration ? (
                      <p>图像生成：{capLabel(caps, 'supports_image_generation')}</p>
                    ) : (
                      <>
                        <p>
                          JSON Object：{capLabel(caps, 'supports_json_object')} · JSON Schema：
                          {capLabel(caps, 'supports_json_schema')}
                        </p>
                        <p>Streaming：{capLabel(caps, 'supports_streaming')}</p>
                        <p>JSON Object 探测：{verified(caps, 'json_object')}</p>
                        <p>JSON Schema 探测：{verified(caps, 'json_schema')}</p>
                      </>
                    )}
                    {probeSummary ? <p className="model-deployment-probe">{probeSummary}</p> : null}
                  </div>
                ),
              },
            ]}
          />
        </div>
        <div className="model-deployment-actions">
          <Button size="small" aria-label="Edit Model" onClick={onEdit}>
            编辑
          </Button>
          <Button size="small" aria-label={deployment.enabled ? 'Disable Model' : 'Enable Model'} onClick={onToggleEnabled}>
            {deployment.enabled ? '禁用' : '启用'}
          </Button>
          <Button size="small" aria-label="Test Model" onClick={onTest}>
            测试
          </Button>
          {onDelete ? (
            <Button size="small" danger aria-label="Delete Model" onClick={onDelete}>
              删除
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  )
}
