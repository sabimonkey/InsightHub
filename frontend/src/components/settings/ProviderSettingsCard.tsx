import { Button, InputNumber, Modal, Switch, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { fetchCoverSettings, fetchMiniMaxTokenPlan, patchCoverSettings, type MiniMaxTokenPlanStatus } from '../../api'
import type { LlmDeployment, LlmProvider } from '../../types'
import { AnalysisBackfillModal } from './AnalysisBackfillModal'
import { AnalysisQueueModal } from './AnalysisQueueModal'
import { CoverQueueModal } from './CoverQueueModal'
import { credentialSourceLabel, providerCredentialLabel, providerKindSubtitle } from '../../lib/settingsModelStatus'
import { ProviderApiKeyActions } from './ProviderApiKeyModal'
import { ModelDeploymentCard } from './ModelDeploymentCard'
import { SettingsStatusChip } from './SettingsStatusChip'
import { CoverPromptEditor } from './CoverPromptEditor'

const { Text } = Typography

type Props = {
  provider: LlmProvider
  routes: Record<string, string>
  workflowNameByKey: Record<string, string>
  statusByDeployment: Record<string, string>
  onAddModel: () => void
  onToggleProvider: () => void
  onRetireProvider: () => void
  onEditDeployment: (deployment: LlmDeployment) => void
  onToggleDeployment: (deployment: LlmDeployment) => void
  onTestDeployment: (deployment: LlmDeployment) => void
  onDeleteDeployment: (deployment: LlmDeployment) => void
  onConfigureApiKey: () => void
  onClearApiKey: () => void
}

export function ProviderSettingsCard({
  provider,
  routes,
  workflowNameByKey,
  statusByDeployment,
  onAddModel,
  onToggleProvider,
  onRetireProvider,
  onEditDeployment,
  onToggleDeployment,
  onTestDeployment,
  onDeleteDeployment,
  onConfigureApiKey,
  onClearApiKey,
}: Props) {
  const credential = providerCredentialLabel(provider)
  const isMinimaxImage = provider.provider_type === 'MINIMAX_IMAGE'
  const isAnalysisProvider = ['ZAI', 'SILICONFLOW'].includes(provider.provider_type)
  const [coverAuto, setCoverAuto] = useState(false)
  const [coverBudget, setCoverBudget] = useState<number | null>(null)
  const [coverBudgetRange, setCoverBudgetRange] = useState<{ min: number; max: number } | null>(null)
  const [coverSettingsLoading, setCoverSettingsLoading] = useState(false)
  const [coverBudgetSaving, setCoverBudgetSaving] = useState(false)
  const [coverNote, setCoverNote] = useState<string | null>(null)
  const [coverNoteStatus, setCoverNoteStatus] = useState<'success' | 'error' | null>(null)
  const [tokenPlan, setTokenPlan] = useState<MiniMaxTokenPlanStatus | null>(null)
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [analysisQueueOpen, setAnalysisQueueOpen] = useState(false)
  const [analysisBackfillOpen, setAnalysisBackfillOpen] = useState(false)

  useEffect(() => {
    if (!isMinimaxImage) return
    let active = true
    setCoverSettingsLoading(true)
    void fetchCoverSettings().then((body) => {
      if (!body.ok) throw new Error(body.message || body.code || '无法读取 MiniMax 配图设置')
      if (active) {
        setCoverAuto(Boolean(body.auto_enabled))
        if (body.monthly_budget != null) setCoverBudget(body.monthly_budget)
        if (body.budget_range) setCoverBudgetRange(body.budget_range)
      }
    }).catch((error: unknown) => {
      if (active) {
        setCoverNote(error instanceof Error ? error.message : '无法读取 MiniMax 配图设置')
        setCoverNoteStatus('error')
      }
    }).finally(() => {
      if (active) setCoverSettingsLoading(false)
    })
    return () => { active = false }
  }, [isMinimaxImage])

  async function saveCoverBudget() {
    if (coverBudget == null || coverBudgetSaving) return
    setCoverBudgetSaving(true)
    setCoverNote(null)
    setCoverNoteStatus(null)
    try {
      const body = await patchCoverSettings(undefined, coverBudget)
      if (!body.ok || body.monthly_budget == null) throw new Error(body.message || body.code || '保存安全上限失败')
      setCoverBudget(body.monthly_budget)
      setCoverBudgetRange(body.budget_range ?? coverBudgetRange)
      setCoverNote(`InsightHub 本地安全上限已保存：${body.monthly_budget} 次尝试/月`)
      setCoverNoteStatus('success')
    } catch (error) {
      setCoverNote(error instanceof Error ? error.message : '保存安全上限失败')
      setCoverNoteStatus('error')
    } finally {
      setCoverBudgetSaving(false)
    }
  }

  async function refreshTokenPlan() {
    setQuotaLoading(true)
    try {
      setTokenPlan(await fetchMiniMaxTokenPlan())
    } finally {
      setQuotaLoading(false)
    }
  }

  return (
    <section className="provider-settings-card" aria-label={`provider ${provider.name}`}>
      <header className="provider-settings-card-header">
        <div className="provider-settings-card-heading">
          <div className="provider-settings-card-titleline">
            <h4 className="provider-settings-card-title">{provider.name}</h4>
            <div className="provider-settings-card-tags">
              <SettingsStatusChip label={credential.label} variant={credential.variant} />
              <SettingsStatusChip
                label={provider.enabled ? 'Provider 已启用' : 'Provider 已禁用'}
                variant={provider.enabled ? 'success' : 'muted'}
              />
            </div>
          </div>
          <Text type="secondary" className="provider-settings-card-subtitle">
            {providerKindSubtitle(provider)}
          </Text>
          {provider.credential_manageable ? (
            <div className="provider-settings-card-credential">
              <Text type="secondary" className="provider-settings-card-credential-source">
                凭据来源：{credentialSourceLabel(provider.credential_source)}
              </Text>
              <ProviderApiKeyActions provider={provider} onConfigure={onConfigureApiKey} onRequestClear={onClearApiKey} />
            </div>
          ) : null}
        </div>
        <div className="provider-settings-card-provider-actions">
          {provider.is_local ? null : (
            <Button size="small" disabled={!provider.enabled && !provider.configured} onClick={onToggleProvider}>
              {provider.enabled ? '停用 Provider' : '启用 Provider'}
            </Button>
          )}
          {['SILICONFLOW', 'DEEPSEEK', 'LOCAL_OPENAI_COMPATIBLE'].includes(provider.provider_type) ? (
            <Button size="small" danger onClick={() => Modal.confirm({
              title: '退役遗留 Provider',
              content: '仅在工作流路由已迁移且没有进行中任务时可退役。历史运行记录会保留。',
              okText: '退役',
              cancelText: '取消',
              onOk: onRetireProvider,
            })}>退役</Button>
          ) : null}
        </div>
      </header>
      <div className="provider-settings-card-models">
        {provider.deployments.length === 0 ? <Text type="secondary">尚未配置模型部署</Text> : null}
        {provider.deployments.map((deployment) => (
          <ModelDeploymentCard
            key={deployment.id}
            provider={provider}
            deployment={deployment}
            routes={routes}
            workflowNameByKey={workflowNameByKey}
            probeSummary={statusByDeployment[deployment.id]}
            onEdit={() => onEditDeployment(deployment)}
            onToggleEnabled={() => onToggleDeployment(deployment)}
            onTest={() => onTestDeployment(deployment)}
            onDelete={() => onDeleteDeployment(deployment)}
          />
        ))}
      </div>
      {isAnalysisProvider ? (
        <div className="provider-settings-card-cover" style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(0,0,0,0.06)' }}>
          <Text strong>批量 AI 分析</Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, flexWrap: 'wrap' }}>
            <Button size="small" onClick={() => setAnalysisBackfillOpen(true)}>
              批量分析未分析资料
            </Button>
            <Button size="small" onClick={() => setAnalysisQueueOpen(true)}>
              查看分析队列
            </Button>
          </div>
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            仅处理正文已就绪且未成功分析（或最近失败）的资料；不会覆盖已有成功分析记录。
          </Text>
          <AnalysisBackfillModal open={analysisBackfillOpen} onClose={() => setAnalysisBackfillOpen(false)} />
          <AnalysisQueueModal open={analysisQueueOpen} onClose={() => setAnalysisQueueOpen(false)} />
        </div>
      ) : null}
      {isMinimaxImage ? (
        <div className="provider-settings-card-cover" style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(0,0,0,0.06)' }}>
          <Text strong>自动配图</Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, flexWrap: 'wrap' }}>
            <Switch
              checked={coverAuto}
              onChange={(checked) => {
                void patchCoverSettings(checked).then((body) => {
                  if (!body.ok) throw new Error(body.message || body.code || '无法保存设置')
                  setCoverAuto(Boolean(body.auto_enabled))
                  setCoverNote(checked ? '已开启自动配图（新资料分析完成后按规则入队）' : '已关闭自动配图（已在队列中的任务不受影响）')
                  setCoverNoteStatus('success')
                }).catch((error: unknown) => {
                  setCoverNote(error instanceof Error ? error.message : '无法保存设置')
                  setCoverNoteStatus('error')
                })
              }}
            />
            <Text type="secondary">
              当前 {coverAuto ? '已开启' : '已关闭'}
              {coverBudget != null ? ` · InsightHub 本地安全上限 ${coverBudget} 次尝试/月` : ''}
            </Text>
            <Button size="small" onClick={() => setQueueOpen(true)}>
              查看配图队列
            </Button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <Text>订阅模式：M Plan Key（仅使用页面安全存储凭据）</Text>
            <Button size="small" loading={quotaLoading} onClick={() => void refreshTokenPlan()}>查询官方套餐用量</Button>
            {tokenPlan ? (
              <Text type={tokenPlan.status === 'AVAILABLE' ? 'success' : 'warning'}>
                {tokenPlan.status === 'AVAILABLE'
                  ? `官方 Token Plan 可用 · 当前窗口 ${tokenPlan.current_interval_usage_count ?? '—'} 次 / 剩余 ${tokenPlan.current_interval_remaining_percent ?? '—'}% · 周窗剩余 ${tokenPlan.weekly_remaining_percent ?? '—'}%（共享额度，非图片张数）`
                  : `官方额度状态：${tokenPlan.status || '未知'}${tokenPlan.code ? ` · ${tokenPlan.code}` : ''}`}
              </Text>
            ) : <Text type="secondary">官方套餐用量尚未在本页面刷新</Text>}
            <InputNumber
              aria-label="InsightHub 本地安全上限"
              min={coverBudgetRange?.min}
              max={coverBudgetRange?.max}
              precision={0}
              step={1}
              disabled={coverSettingsLoading || coverBudgetSaving || coverBudgetRange == null}
              value={coverBudget ?? undefined}
              onChange={(value) => { setCoverBudget(value == null ? null : Number(value)) }}
            />
            <Button size="small" loading={coverBudgetSaving} disabled={coverSettingsLoading || coverBudgetRange == null || coverBudget == null} onClick={() => void saveCoverBudget()}>
              保存安全上限
            </Button>
          </div>
          {coverNote ? (
            <Text type={coverNoteStatus === 'error' ? 'danger' : coverNoteStatus === 'success' ? 'success' : 'secondary'} role={coverNoteStatus === 'error' ? 'alert' : 'status'} style={{ display: 'block', marginTop: 8 }}>
              {coverNote}
            </Text>
          ) : null}
          <CoverPromptEditor />
          <CoverQueueModal open={queueOpen} onClose={() => setQueueOpen(false)} />
        </div>
      ) : null}
      <footer className="provider-settings-card-footer">
          <Button type="dashed" size="small" onClick={onAddModel} disabled={!provider.configured && !provider.is_local && provider.provider_type !== 'ZAI'}>
          + 添加模型
        </Button>
        {!provider.configured && !provider.is_local && provider.provider_type !== 'FAKE' && provider.provider_type !== 'ZAI' ? (
          <Text type="secondary">请先完成 Provider 配置后再添加模型。</Text>
        ) : null}
      </footer>
    </section>
  )
}
