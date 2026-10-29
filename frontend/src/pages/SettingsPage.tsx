import { Button, Card, Collapse, Modal, Typography } from 'antd'
import { useEffect, useState } from 'react'
import type { SettingsSection } from '../lib/appNavigation'
import {
  createDeployment,
  deleteDeployment,
  fetchDeleteDeploymentPreview,
  fetchProviders,
  fetchRoutes,
  saveRoutes,
  retireProvider,
  setProviderEnabled,
  testDeployment,
  updateDeployment,
} from '../api'
import { ClearProviderCredentialModal, ProviderApiKeyModal } from '../components/settings/ProviderApiKeyModal'
import { ProviderSettingsCard } from '../components/settings/ProviderSettingsCard'
import type { DeploymentProbeResult, LlmDeployment, LlmProvider, WorkflowRouteOption } from '../types'

const { Title, Paragraph, Text } = Typography

const WORKFLOWS = [
  ['EXTRACTION_AI', 'AI 文件理解'],
  ['ANALYSIS', '资料分析'],
  ['ASK_PLANNER', '问答规划'],
  ['ASK_ANSWER', '问答回答'],
  ['BRIEF', '笔记生成'],
] as const

function verifiedStatus(caps: Record<string, unknown> | undefined, probe: string) {
  const value = caps?.[`verified_${probe}`]
  return value ? String(value) : '—'
}

function formatProbeSummary(result: DeploymentProbeResult) {
  if (result.provider_type === 'MINIMAX_IMAGE' || result.mode) {
    const modeLabel =
      result.mode === 'fake' ? '模拟测试（不调用真实 MiniMax）' : result.mode === 'sample_generation' ? '真实生图样本' : result.message
    return [
      result.overall_status ?? (result.ok ? 'PASS' : 'FAIL'),
      result.mode || 'image',
      result.model,
      result.latency_ms ? `${result.latency_ms} ms` : '',
      modeLabel,
    ]
      .filter(Boolean)
      .join(' / ')
  }
  const overall = result.overall_status ?? (result.ok ? 'PASS' : 'FAIL')
  return [
    overall,
    result.code ?? result.message ?? result.error ?? '',
    `Chat: ${result.probes?.chat?.status ?? '—'}`,
    `UTF-8: ${result.probes?.utf8?.status ?? '—'}`,
    `JSON Object: ${result.probes?.json_object?.status ?? '—'}`,
    `JSON Schema: ${result.probes?.json_schema?.status ?? '—'}`,
    `Streaming: ${result.probes?.streaming?.status ?? '—'}`,
    result.model,
    result.total_latency_ms ? `${result.total_latency_ms} ms` : result.latency_ms ? `${result.latency_ms} ms` : '',
  ]
    .filter(Boolean)
    .join(' / ')
}

type DeploymentCapabilities = {
  supports_json_object?: boolean
  supports_json_schema?: boolean
  supports_streaming?: boolean
  context_window?: number | null
  default_max_output_tokens?: number | null
  timeout_seconds?: number | null
  supports_multimodal?: boolean
  supports_reasoning?: boolean
}

type SystemStatus = {
  version: string
  backend: string
  postgres: string
  redis: string
  worker: string
  alembic: { revision: string | null; ok: boolean }
  raw_storage: string
  disk: { path: string; used: number; available: number; warning: boolean }
  counts: Record<string, number>
  optional: { llm_configured: boolean; embedding_configured: boolean }
  latest_backup: string | null
  backup_command: string
}

const NAV_GROUPS: Array<{ title: string; items: Array<{ id: SettingsSection; label: string }> }> = [
  {
    title: '常用设置',
    items: [
      { id: 'overview', label: '概览' },
      { id: 'models', label: 'AI 模型' },
      { id: 'routes', label: '工作流路由' },
    ],
  },
  {
    title: '系统管理',
    items: [
      { id: 'runtime', label: '运行状态' },
      { id: 'advanced', label: '高级设置' },
    ],
  },
]

const SECTION_TITLES: Record<SettingsSection, string> = {
  overview: '设置概览',
  models: 'AI 模型',
  routes: '工作流路由',
  runtime: '运行状态',
  advanced: '高级设置',
}

type SettingsPageProps = {
  section: SettingsSection
  onSectionChange: (section: SettingsSection) => void
}

export function SettingsPage({ section, onSectionChange }: SettingsPageProps) {
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [routes, setRoutes] = useState<Record<string, string>>({})
  const [routeOptions, setRouteOptions] = useState<WorkflowRouteOption[]>([])
  const [status, setStatus] = useState<Record<string, string>>({})
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [recoverNote, setRecoverNote] = useState('')
  const [cloudNote, setCloudNote] = useState('')
  const [routeNote, setRouteNote] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('bge-m3-local')
  const [editDeployment, setEditDeployment] = useState<LlmDeployment | null>(null)
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editCapabilities, setEditCapabilities] = useState<DeploymentCapabilities>({})
  const [apiKeyProvider, setApiKeyProvider] = useState<LlmProvider | null>(null)
  const [clearApiKeyProvider, setClearApiKeyProvider] = useState<LlmProvider | null>(null)
  const [coverAudit, setCoverAudit] = useState<{ buckets?: Record<string, { count: number }>; monthly_used?: number; monthly_attempts?: number; monthly_budget?: number } | null>(null)
  const [coverBackfillNote, setCoverBackfillNote] = useState('')

  function reloadProviders() {
    return fetchProviders().then(setProviders).catch(() => setProviders([]))
  }

  useEffect(() => {
    void reloadProviders()
    void fetchRoutes()
      .then(({ routes: rows, options }) => {
        const next: Record<string, string> = {}
        for (const row of rows) next[row.workflow] = row.deployment_id
        setRoutes(next)
        setRouteOptions(options)
      })
      .catch(() => {
        setRoutes({})
        setRouteOptions([])
      })
    void fetch('/api/embedding/profiles')
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { profiles?: Array<{ model: string; is_active: boolean }> } | null) => {
        const active = body?.profiles?.find((item) => item.is_active)
        if (active?.model) setEmbeddingModel(active.model)
      })
      .catch(() => setEmbeddingModel('bge-m3-local'))
    void fetch('/api/system')
      .then((response) => response.json())
      .then((body: SystemStatus) => setSystem(body))
      .catch(() => setSystem(null))
  }, [])

  function optionById(deploymentId: string | undefined) {
    return routeOptions.find((item) => item.deployment_id === deploymentId)
  }

  function chooseRoute(workflow: string, deploymentId: string) {
    const previous = optionById(routes[workflow])
    const next = optionById(deploymentId)
    if (previous?.is_local && next && !next.is_local) {
      setCloudNote('该工作流发送给模型的文本内容将提交到配置的外部 API。')
    }
    setRoutes((current) => ({ ...current, [workflow]: deploymentId }))
  }

  function addModel(provider: LlmProvider) {
    const displayName = window.prompt('Display Name')
    if (!displayName) return
    const modelId = window.prompt('Model ID（完整模型 ID）')
    if (!modelId) return
    void createDeployment(provider.id, { display_name: displayName, model_id: modelId })
      .then(() => reloadProviders())
      .then(() => fetchRoutes())
      .then(({ routes: rows, options }) => {
        const next: Record<string, string> = {}
        for (const row of rows) next[row.workflow] = row.deployment_id
        setRoutes(next)
        setRouteOptions(options)
        setRouteNote('Model added')
      })
      .catch((error: Error) => setRouteNote(error.message))
  }

  function openEditModel(deployment: LlmDeployment) {
    const caps = (deployment.capabilities ?? {}) as DeploymentCapabilities
    setEditDeployment(deployment)
    setEditDisplayName(deployment.display_name)
    setEditCapabilities({
      supports_json_object: caps.supports_json_object === true,
      supports_json_schema: caps.supports_json_schema === true,
      supports_streaming: caps.supports_streaming === true,
      context_window: typeof caps.context_window === 'number' ? caps.context_window : null,
      default_max_output_tokens: typeof caps.default_max_output_tokens === 'number' ? caps.default_max_output_tokens : null,
      timeout_seconds: typeof caps.timeout_seconds === 'number' ? caps.timeout_seconds : null,
      supports_multimodal: caps.supports_multimodal === true,
      supports_reasoning: caps.supports_reasoning === true,
    })
  }

  function confirmDeleteModel(deployment: LlmDeployment) {
    void fetchDeleteDeploymentPreview(deployment.id)
      .then((preview) => {
        if (!preview.ok) {
          setRouteNote(preview.code || '无法删除')
          return
        }
        const routes = preview.routes?.length ? preview.routes.join(', ') : '无'
        Modal.confirm({
          title: '确认删除模型部署？',
          content: (
            <div>
              <p>Provider：{preview.provider_name}</p>
              <p>Model ID：{preview.model_id}</p>
              <p>工作流引用：{routes}</p>
              <p>历史分析记录将保留，不会被删除。</p>
              {!preview.can_delete ? <p style={{ color: '#cf1322' }}>该部署仍被工作流引用，请先切换路由。</p> : null}
            </div>
          ),
          okText: '删除',
          okButtonProps: { danger: true, disabled: !preview.can_delete },
          cancelText: '取消',
          onOk: () =>
            deleteDeployment(deployment.id)
              .then(() => reloadProviders())
              .then(() => setRouteNote('Model deleted')),
        })
      })
      .catch((error: Error) => setRouteNote(error.message))
  }

  function saveEditModel() {
    if (!editDeployment) return
    const merged = {
      ...(editDeployment.capabilities ?? {}),
      ...editCapabilities,
      capability_declared_manual: true,
    }
    void updateDeployment(editDeployment.id, { display_name: editDisplayName, capabilities: merged })
      .then(() => reloadProviders())
      .then(() => {
        setEditDeployment(null)
        setRouteNote('Model updated')
      })
      .catch((error: Error) => setRouteNote(error.message))
  }

  function workflowEligibilityLabel(option: WorkflowRouteOption | undefined) {
    if (!option?.eligible_workflows) return ''
    const labels: string[] = []
    if (option.eligible_workflows.ANALYSIS) labels.push('Analysis')
    if (option.eligible_workflows.ASK_PLANNER) labels.push('Planner')
    if (option.eligible_workflows.ASK_ANSWER) labels.push('Ask Answer')
    if (option.eligible_workflows.BRIEF) labels.push('Brief')
    if (labels.length === 4) return 'Eligible: all workflows'
    if (labels.length === 1 && labels[0] === 'Ask Answer') return 'Eligible: Ask Answer only'
    return labels.length ? `Eligible: ${labels.join(', ')}` : 'Eligible: none (structured output missing)'
  }

  function routeSummary(workflow: string) {
    const selected = optionById(routes[workflow])
    if (!selected) return '—'
    return `${selected.provider_name ?? ''} · ${selected.deployment_display_name || selected.model} · ${selected.is_local ? '本地' : '云端'}${selected.configured ? '' : '（未配置）'}`
  }

  const overviewPanel = (
    <Card title="当前配置摘要">
      <p>资料分析（ANALYSIS）：{routeSummary('ANALYSIS')}</p>
      <p>问答规划（ASK_PLANNER）：{routeSummary('ASK_PLANNER')}</p>
      <p>问答回答（ASK_ANSWER）：{routeSummary('ASK_ANSWER')}</p>
      <p>笔记生成（BRIEF）：{routeSummary('BRIEF')}</p>
      <p>知识检索 Embedding：{embeddingModel} · 本地 · {system?.optional.embedding_configured ? '已配置' : '未配置'}</p>
      <p>
        系统运行：
        {system
          ? system.backend === 'ok' && system.postgres === 'ok' && system.raw_storage === 'ok'
            ? ' 核心服务正常'
            : ' 需要检查'
          : ' 不可用'}
      </p>
      <p>后台 Worker：{system?.worker === 'running' ? '运行中' : '未检测到'}</p>
      <Paragraph type="secondary">云端 Provider 显示“已配置”仅表示密钥或端点已设置，不代表已在线连通。</Paragraph>
      <div className="settings-overview-links">
        <Button type="link" onClick={() => onSectionChange('models')}>
          管理 AI 模型
        </Button>
        <Button type="link" onClick={() => onSectionChange('routes')}>
          管理工作流路由
        </Button>
        <Button type="link" onClick={() => onSectionChange('runtime')}>
          查看运行状态
        </Button>
      </div>
    </Card>
  )

  const runtimePanel = system ? (
        <Card title="系统状态" aria-label="system status">
          <p>{system.backend === 'ok' && system.postgres === 'ok' && system.raw_storage === 'ok' ? '● 系统服务正常' : '● 需要检查'}</p>
          <p>● 知识检索 BGE-M3 · 本地 · {embeddingModel ? '已配置' : '—'}</p>
          <p>● 数据库{system.postgres === 'ok' ? '正常' : '异常'}</p>
          <p>● 后台任务{system.worker === 'running' ? '正常' : '未检测到'}</p>
          <p>● 存储{system.raw_storage === 'ok' ? '正常' : '异常'}</p>
          {system.disk.warning ? <p>磁盘空间不足，未删除任何资料。</p> : null}
          <Collapse
            items={[
              {
                key: 'advanced',
                label: '高级系统信息',
                children: (
                  <div>
                    <p>Version：{system.version}</p>
                    <p>Backend：{system.backend}</p>
                    <p>PostgreSQL：{system.postgres}</p>
                    <p>Redis：{system.redis}</p>
                    <p>Worker：{system.worker}</p>
                    <p>Alembic：{system.alembic.revision ?? 'unknown'}</p>
                    <p>Disk：{system.disk.path}</p>
                    <p>
                      Sources {system.counts.sources} / Chunks {system.counts.chunks} / Claims {system.counts.claims} / Embeddings {system.counts.embeddings} / Briefs {system.counts.briefs}
                    </p>
                    <p>Backup：{system.backup_command}</p>
                    <p>Latest backup：{system.latest_backup ?? 'none'}</p>
                  </div>
                ),
              },
            ]}
          />
          <Button
            onClick={() => {
              void fetch('/api/system/recover', { method: 'POST' })
                .then((response) => response.json())
                .then((body: { count: number }) => setRecoverNote(`已恢复 ${body.count} 个任务`))
            }}
          >
            恢复卡住的任务
          </Button>
          {recoverNote ? <p>{recoverNote}</p> : null}
        </Card>
      ) : (
        <p>系统状态不可用</p>
      )

  const advancedPanel = (
    <>
      <Card title="知识库配图" aria-label="cover automation">
        <p>自动配图由环境变量控制（COVER_AUTO_ENABLED、COVER_AUTO_REQUIRES_ANALYSIS、COVER_MONTHLY_BUDGET）。开发/测试默认不自动调用真实 MiniMax。</p>
        <Button
          onClick={() => {
            void fetch('/api/cover/audit')
              .then((response) => (response.ok ? response.json() : null))
              .then((body) => setCoverAudit(body))
          }}
        >
          查看缺图漏斗（只读）
        </Button>
        {coverAudit?.buckets ? (
          <div style={{ marginTop: 12 }}>
            {Object.entries(coverAudit.buckets).map(([key, row]) => (
              <p key={key}>
                {key}：{row.count}
              </p>
            ))}
            <p>
              本月项目配图尝试：{coverAudit.monthly_attempts ?? coverAudit.monthly_used ?? 0}；InsightHub 本地安全上限：{coverAudit.monthly_budget ?? '—'} 次/月（不是 MiniMax 套餐额度）
            </p>
          </div>
        ) : null}
        <Button
          style={{ marginTop: 8 }}
          onClick={() => {
            const eligible = coverAudit?.buckets?.eligible_missing_cover?.count ?? 0
            if (!window.confirm(`将为最多 ${eligible} 条符合条件且缺封面的 USER 资料入队（受月度额度限制）。确认？`)) return
            void fetch('/api/cover/backfill', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ confirm: true, retry_failed_only: false }),
            })
              .then(async (response) => response.json())
              .then((body) => setCoverBackfillNote(body.ok ? `已入队 ${body.enqueued_run_ids?.length ?? 0} 个任务` : body.message || body.code))
          }}
        >
          补齐缺失配图（需确认）
        </Button>
        {coverBackfillNote ? <p>{coverBackfillNote}</p> : null}
      </Card>
      <Card title="知识检索模型" aria-label="embedding provider">
        <p>BGE-M3 · 本地 · 1024 维</p>
        <p>当前配置：{embeddingModel}</p>
        <Paragraph type="secondary">知识检索向量与聊天模型路由相互独立。</Paragraph>
      </Card>
      <Card title="资料分类">
        <p>默认类别 project_discovery、business、knowledge、other 不能删除。可以新增自定义类别。</p>
        <Button
          onClick={() => {
            const name = window.prompt('新类别名称')
            if (!name) return
            void fetch('/api/categories', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name, display_order: 10 }),
            })
          }}
        >
          Add Category
        </Button>
      </Card>
    </>
  )

  const workflowNameByKey = Object.fromEntries(WORKFLOWS) as Record<string, string>

  const modelsPanel = (
    <div className="settings-models-panel">
      <Paragraph type="secondary">每个 Provider 独立成卡；模型部署在 Provider 内管理，操作按钮位于模型行右侧。</Paragraph>
      {routeNote ? <Paragraph type="secondary">{routeNote}</Paragraph> : null}
      {providers.length === 0 ? <Text type="secondary">尚未配置 LLM Provider</Text> : null}
      {providers.map((provider) => (
        <ProviderSettingsCard
          key={provider.id}
          provider={provider}
          routes={routes}
          workflowNameByKey={workflowNameByKey}
          statusByDeployment={status}
          onAddModel={() => addModel(provider)}
          onToggleProvider={() => {
            void setProviderEnabled(provider.id, !provider.enabled)
              .then(() => reloadProviders())
              .catch((error: Error) => setRouteNote(error.message))
          }}
          onRetireProvider={() => {
            void retireProvider(provider.id)
              .then(() => reloadProviders())
              .catch((error: Error) => setRouteNote(error.message))
          }}
          onEditDeployment={openEditModel}
          onToggleDeployment={(deployment) => {
            void updateDeployment(deployment.id, { enabled: !deployment.enabled })
              .then(() => reloadProviders())
              .catch((error: Error) => setRouteNote(error.message))
          }}
          onTestDeployment={(deployment) => {
            void testDeployment(deployment.id).then((result) => {
              setStatus((current) => ({ ...current, [deployment.id]: formatProbeSummary(result) }))
              void reloadProviders()
            })
          }}
          onDeleteDeployment={confirmDeleteModel}
          onConfigureApiKey={() => setApiKeyProvider(provider)}
          onClearApiKey={() => setClearApiKeyProvider(provider)}
        />
      ))}
      <ProviderApiKeyModal
        open={apiKeyProvider !== null}
        provider={apiKeyProvider}
        onClose={() => setApiKeyProvider(null)}
        onSaved={() => void reloadProviders()}
      />
      <ClearProviderCredentialModal
        open={clearApiKeyProvider !== null}
        provider={clearApiKeyProvider}
        onClose={() => setClearApiKeyProvider(null)}
        onCleared={() => void reloadProviders()}
      />
      <Modal
        title="编辑模型"
        open={editDeployment !== null}
        onCancel={() => setEditDeployment(null)}
        onOk={() => saveEditModel()}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        {editDeployment ? (
          <div aria-label="edit model">
            <p>
              <label>
                Display Name{' '}
                <input aria-label="Display Name" value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} />
              </label>
            </p>
            <p>
              Model ID <input aria-label="Model ID" readOnly value={editDeployment.model_id} />
            </p>
            <p>Capabilities (declared values; use Test Model for verified probe results)</p>
            <p>
              JSON Object current: {editCapabilities.supports_json_object ? 'Yes' : 'No'} / verified:{' '}
              {verifiedStatus(editDeployment.capabilities, 'json_object')}
              <label>
                {' '}
                Manual override{' '}
                <input
                  type="checkbox"
                  aria-label="JSON Object manual"
                  checked={editCapabilities.supports_json_object === true}
                  onChange={(event) => setEditCapabilities((current) => ({ ...current, supports_json_object: event.target.checked }))}
                />
              </label>
            </p>
            <p>
              JSON Schema current: {editCapabilities.supports_json_schema ? 'Yes' : 'No'} / verified:{' '}
              {verifiedStatus(editDeployment.capabilities, 'json_schema')}
              <label>
                {' '}
                Manual override{' '}
                <input
                  type="checkbox"
                  aria-label="JSON Schema manual"
                  checked={editCapabilities.supports_json_schema === true}
                  onChange={(event) => setEditCapabilities((current) => ({ ...current, supports_json_schema: event.target.checked }))}
                />
              </label>
            </p>
            <p>
              Streaming current: {editCapabilities.supports_streaming ? 'Yes' : 'No'} / verified:{' '}
              {verifiedStatus(editDeployment.capabilities, 'streaming')}
              <label>
                {' '}
                Manual override{' '}
                <input
                  type="checkbox"
                  aria-label="Streaming manual"
                  checked={editCapabilities.supports_streaming === true}
                  onChange={(event) => setEditCapabilities((current) => ({ ...current, supports_streaming: event.target.checked }))}
                />
              </label>
            </p>
            <p>
              Context Window{' '}
              <input
                aria-label="Context Window"
                value={editCapabilities.context_window ?? ''}
                onChange={(event) =>
                  setEditCapabilities((current) => ({
                    ...current,
                    context_window: event.target.value ? Number(event.target.value) : null,
                  }))
                }
              />
            </p>
            <p>
              Max Output{' '}
              <input
                aria-label="Max Output"
                value={editCapabilities.default_max_output_tokens ?? ''}
                onChange={(event) =>
                  setEditCapabilities((current) => ({
                    ...current,
                    default_max_output_tokens: event.target.value ? Number(event.target.value) : null,
                  }))
                }
              />
            </p>
            <p>
              Timeout Seconds{' '}
              <input
                aria-label="Timeout Seconds"
                value={editCapabilities.timeout_seconds ?? ''}
                onChange={(event) =>
                  setEditCapabilities((current) => ({
                    ...current,
                    timeout_seconds: event.target.value ? Number(event.target.value) : null,
                  }))
                }
              />
            </p>
          </div>
        ) : null}
      </Modal>
    </div>
  )

  const routesPanel = (
      <Card title="任务模型" aria-label="ai routing">
        {WORKFLOWS.map(([workflow, label]) => {
          const selected = optionById(routes[workflow])
          return (
            <p key={workflow}>
              <label>
                {label}{' '}
                <select aria-label={`${label} route`} value={routes[workflow] ?? ''} onChange={(event) => chooseRoute(workflow, event.target.value)}>
                  {(routes[workflow] ? [] : [{ deployment_id: '', label: '—' }]).map((item) => (
                    <option key="empty" value="">
                      {item.label}
                    </option>
                  ))}
                  {routeOptions.map((option) => (
                    <option key={option.deployment_id} value={option.deployment_id} disabled={!option.enabled || !option.configured}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <br />
              <span aria-label={`${label} summary`}>
                {selected
                  ? `${selected.provider_name ?? ''} · ${selected.deployment_display_name || selected.model} · ${selected.is_local ? '本地' : '云端'}`
                  : '—'}
              </span>{' '}
              <span>{selected?.status === 'CONFIGURATION_REQUIRED' ? '（CONFIGURATION_REQUIRED：请先配置智谱 GLM API Key）' : selected?.status === 'DISABLED' ? '（模型已禁用：在模型卡中显式启用后可运行）' : ''}</span>{' '}
              <span>{workflowEligibilityLabel(selected)}</span>
            </p>
          )
        })}
        {cloudNote ? <p>{cloudNote}</p> : null}
        {routeNote ? <p>{routeNote}</p> : null}
        <Button
          onClick={() => {
            const body = {
              EXTRACTION_AI: routes.EXTRACTION_AI,
              ANALYSIS: routes.ANALYSIS,
              ASK_PLANNER: routes.ASK_PLANNER,
              ASK_ANSWER: routes.ASK_ANSWER,
              BRIEF: routes.BRIEF,
            }
            void saveRoutes(body)
              .then(({ routes: rows, options }) => {
                const next: Record<string, string> = {}
                for (const row of rows) next[row.workflow] = row.deployment_id
                setRoutes(next)
                setRouteOptions(options)
                setRouteNote('AI Routing saved')
              })
              .catch((error: Error) => setRouteNote(error.message))
          }}
        >
          保存任务模型路由
        </Button>
      </Card>
  )

  let content = overviewPanel
  if (section === 'models') content = modelsPanel
  if (section === 'routes') content = routesPanel
  if (section === 'runtime') content = runtimePanel
  if (section === 'advanced') content = advancedPanel

  return (
    <main className="app-page settings-layout" data-testid="settings-layout">
      <aside className="settings-nav" aria-label="设置导航">
        <Title level={4} style={{ marginTop: 0 }}>
          设置
        </Title>
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="settings-nav-group">
            <Text type="secondary" className="settings-nav-group-title">
              {group.title}
            </Text>
            <ul className="settings-nav-list">
              {group.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={section === item.id ? 'settings-nav-item active' : 'settings-nav-item'}
                    aria-current={section === item.id ? 'page' : undefined}
                    onClick={() => onSectionChange(item.id)}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>
      <section className="settings-content" aria-label="设置内容">
        <Title level={3} className="settings-content-title">
          {SECTION_TITLES[section]}
        </Title>
        {content}
      </section>
    </main>
  )
}
