import { Alert, Button, Input, Modal, Select, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchCoverPrompt, fetchCoverStatus, reviewCoverCandidate, startCoverGenerate, type CoverStatusResponse } from '../../api'
import { coverStageLabel } from '../../lib/coverStageLabel'

const { Paragraph, Text } = Typography
const MAX_PROMPT_CHARS = 1500

type Props = {
  sourceId: string | null
  title?: string
  open: boolean
  onClose: () => void
  onDone?: () => void
}

function promptLength(value: string): number {
  return value.replace(/\s+/g, ' ').trim().length
}

export function GenerateCoverModal({ sourceId, title, open, onClose, onDone }: Props) {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('')
  const [usable, setUsable] = useState(true)
  const [uiPhase, setUiPhase] = useState<'idle' | 'running' | 'done' | 'failed'>('idle')
  const [runId, setRunId] = useState<string | null>(null)
  const [stageLabel, setStageLabel] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [ready, setReady] = useState(false)
  const [maxChars, setMaxChars] = useState(MAX_PROMPT_CHARS)
  const [promptRevision, setPromptRevision] = useState<number | undefined>()
  const [promptPreviewToken, setPromptPreviewToken] = useState<string | undefined>()
  const [currentCoverUrl, setCurrentCoverUrl] = useState<string | null>(null)
  const [candidateCoverUrl, setCandidateCoverUrl] = useState<string | null>(null)
  const [currentPreviewBroken, setCurrentPreviewBroken] = useState(false)
  const [candidatePreviewBroken, setCandidatePreviewBroken] = useState(false)
  const [candidatePreviewLoaded, setCandidatePreviewLoaded] = useState(false)
  const [colorScheme, setColorScheme] = useState('auto')
  const [budgetUsed, setBudgetUsed] = useState<number | null>(null)
  const [monthlyBudget, setMonthlyBudget] = useState<number | null>(null)
  const [budgetAvailable, setBudgetAvailable] = useState(true)
  const [confirmAgainOpen, setConfirmAgainOpen] = useState(false)
  const submitLock = useRef(false)
  const pendingRequestKey = useRef<{ sourceId: string; key: string } | null>(null)

  const charCount = useMemo(() => promptLength(prompt), [prompt])
  const tooLong = charCount > maxChars

  const showCandidate = useCallback((body: CoverStatusResponse) => {
    if (body.current_cover_url || body.cover_url) setCurrentCoverUrl(body.current_cover_url || body.cover_url || null)
    if (body.lifecycle === 'running') {
      setRunId(body.run_id || null)
      setStageLabel(coverStageLabel(body.stage, body.status))
      setUiPhase('running')
      return
    }
    if (body.lifecycle === 'failed') {
      setRunId(body.run_id || null)
      setUiPhase('failed')
      setCandidateCoverUrl(null)
      setError(body.error_message || body.error_code || '生成失败；当前封面保持不变。')
      return
    }
    if (
      body.lifecycle === 'succeeded'
      && body.candidate_cover_url
      && !body.candidate_is_current
      && !body.candidate_review_state
    ) {
      setRunId(body.run_id || null)
      setCandidateCoverUrl(body.candidate_cover_url)
      setCandidatePreviewBroken(false)
      setCandidatePreviewLoaded(false)
      setUiPhase('done')
      setError(null)
      return
    }
    setRunId(null)
    setCandidateCoverUrl(null)
    setUiPhase('idle')
  }, [])

  useEffect(() => {
    if (!open || !sourceId) return
    let cancelled = false
    setReady(false)
    setError(null)
    setCurrentPreviewBroken(false)
    setCandidatePreviewBroken(false)
    setCandidatePreviewLoaded(false)
    setCurrentCoverUrl(null)
    setCandidateCoverUrl(null)
    setRunId(null)
    setUiPhase('idle')
    setColorScheme('auto')
    void Promise.all([fetchCoverPrompt(sourceId, 'auto'), fetchCoverStatus(sourceId)])
      .then(([promptBody, statusBody]) => {
        if (cancelled) return
        if (!promptBody.ok) {
          setError(promptBody.message || '无法加载配图信息')
          return
        }
        setPrompt(promptBody.prompt || '')
        setPromptRevision(promptBody.prompt_revision)
        setPromptPreviewToken(promptBody.prompt_preview_token)
        setCurrentCoverUrl(statusBody.current_cover_url || statusBody.cover_url || promptBody.current_cover_url || null)
        setModel(promptBody.model || '')
        setProvider(promptBody.provider || '')
        setUsable(promptBody.content_usable !== false)
        if (promptBody.max_prompt_chars) setMaxChars(promptBody.max_prompt_chars)
        setBudgetUsed(promptBody.budget_used ?? null)
        setMonthlyBudget(promptBody.monthly_budget ?? null)
        setBudgetAvailable(promptBody.budget_available !== false)
        showCandidate(statusBody)
        setReady(true)
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message)
      })
    return () => {
      cancelled = true
    }
  }, [open, sourceId, showCandidate])

  useEffect(() => {
    if (!open || !sourceId || uiPhase !== 'running' || !runId) return
    let cancelled = false
    const timer = window.setInterval(() => {
      void fetchCoverStatus(sourceId, runId).then((body) => {
        if (!cancelled && body.ok) showCandidate(body)
      }).catch(() => { if (!cancelled) setError('暂时无法读取任务状态，请稍后刷新。') })
    }, 1500)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [open, sourceId, uiPhase, runId, showCandidate])

  function submitGeneration() {
    if (!sourceId || !ready || !usable || tooLong || !budgetAvailable || submitLock.current || uiPhase === 'running') return
    submitLock.current = true
    setLoading(true)
    setError(null)
    setCandidateCoverUrl(null)
    setCandidatePreviewBroken(false)
    setCandidatePreviewLoaded(false)
    setUiPhase('running')
    setStageLabel('正在提交生成任务…')
    const idempotencyKey = pendingRequestKey.current?.sourceId === sourceId
      ? pendingRequestKey.current.key : crypto.randomUUID()
    pendingRequestKey.current = { sourceId, key: idempotencyKey }
    void startCoverGenerate(sourceId, {
      prompt,
      confirm_send: true,
      color_scheme: colorScheme,
      idempotency_key: idempotencyKey,
      prompt_revision: promptRevision,
      prompt_preview_token: promptPreviewToken,
    })
      .then((body) => {
        pendingRequestKey.current = null
        if (!body.ok) {
          setUiPhase('failed')
          setError(body.message || body.code || '无法开始生成；当前封面保持不变。')
          return
        }
        showCandidate(body)
        void fetchCoverPrompt(sourceId, colorScheme).then((current) => {
          if (current.ok) {
            setBudgetUsed(current.budget_used ?? null)
            setMonthlyBudget(current.monthly_budget ?? null)
            setBudgetAvailable(current.budget_available !== false)
          }
        }).catch(() => { /* The server still enforces the budget on submission. */ })
      })
      .catch((exc: Error) => {
        setUiPhase('failed')
        setError(exc.message)
      })
      .finally(() => {
        submitLock.current = false
        setLoading(false)
      })
  }

  async function changeColorScheme(value: string) {
    setColorScheme(value)
    if (!sourceId) return
    try {
      const body = await fetchCoverPrompt(sourceId, value)
      if (body.ok && body.prompt) {
        setPrompt(body.prompt)
        setPromptRevision(body.prompt_revision)
        setPromptPreviewToken(body.prompt_preview_token)
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '无法加载配色提示词')
    }
  }

  async function prepareAnotherGeneration() {
    if (!sourceId || loading) return
    setLoading(true)
    setError(null)
    try {
      // Automatic palette choice depends on recent cover history, which changes
      // after each successful run. Refresh the exact server preview and token
      // before asking the user to authorize another paid attempt.
      const body = await fetchCoverPrompt(sourceId, colorScheme)
      if (!body.ok) {
        setError(body.message || '无法刷新配图预览')
        return
      }
      setPrompt(body.prompt || '')
      setPromptRevision(body.prompt_revision)
      setPromptPreviewToken(body.prompt_preview_token)
      setBudgetUsed(body.budget_used ?? null)
      setMonthlyBudget(body.monthly_budget ?? null)
      setBudgetAvailable(body.budget_available !== false)
      setConfirmAgainOpen(true)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '无法刷新配图预览')
    } finally {
      setLoading(false)
    }
  }

  async function reviewCandidate(action: 'keep_old' | 'use_new') {
    if (!runId || loading) return
    setLoading(true)
    setError(null)
    try {
      const body = await reviewCoverCandidate(runId, action)
      if (!body.ok) {
        setError(body.message || body.code || '保存封面选择失败')
        return
      }
      onDone?.()
      onClose()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '保存封面选择失败')
    } finally {
      setLoading(false)
    }
  }

  const footer = uiPhase === 'done' && candidateCoverUrl ? [
    <Button key="keep" disabled={loading} onClick={() => void reviewCandidate('keep_old')}>保留旧图</Button>,
    <Button key="again" loading={loading} disabled={loading} onClick={() => void prepareAnotherGeneration()}>再生成一张</Button>,
    <Button key="use" type="primary" loading={loading} disabled={!candidatePreviewLoaded || candidatePreviewBroken} onClick={() => void reviewCandidate('use_new')}>使用新图</Button>,
  ] : uiPhase === 'running' ? [
    <Button key="close" onClick={onClose}>关闭</Button>,
  ] : [
    <Button key="cancel" onClick={onClose}>取消</Button>,
    <Button
      key="go"
      type="primary"
      loading={loading}
      disabled={!ready || !usable || tooLong || !budgetAvailable}
      onClick={submitGeneration}
    >
      {uiPhase === 'failed' ? '确认重试生成' : currentCoverUrl ? '确认重新生成' : '确认生成封面'}
    </Button>,
  ]

  return (
    <>
      <Modal
        title={currentCoverUrl ? '重新生成封面' : '生成封面'}
        open={open}
        width={uiPhase === 'done' ? 760 : 560}
        style={{ top: 24 }}
        styles={{ body: { maxHeight: 'calc(100dvh - 180px)', overflowY: 'auto', paddingRight: 8 } }}
        onCancel={onClose}
        footer={footer}
        destroyOnClose
      >
        <Paragraph type="secondary">
          打开弹窗和调整配色只会读取本地资料与项目额度状态，不会发送生图请求。点击确认后才会向 MiniMax 提交主题描述。
        </Paragraph>
        <Paragraph type="secondary">
          生成结果先作为候选封面保存；在点击“使用新图”前，知识库继续展示当前封面。候选图与历史文件分别保存。
        </Paragraph>
        {budgetUsed !== null && monthlyBudget !== null ? (
          <Alert
            type={budgetAvailable ? 'info' : 'warning'}
            showIcon
            message={`本月 InsightHub 本地安全次数上限：已用 ${budgetUsed}/${monthlyBudget} 次生成尝试`}
            description="这是项目本地安全上限，不是 MiniMax 官方套餐剩余额度；失败尝试也计入上限。"
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <Paragraph type="secondary">确认后会向 MiniMax 发起一次生图请求，可能消耗订阅额度；额度以官方查询结果为准。若订阅额度不可用或接口不兼容，系统会报错，不会切换到旧按量付费凭据。</Paragraph>
        <p><Text strong>资料：</Text> {title || sourceId}</p>
        <p><Text strong>图像模型：</Text> {provider ? `${provider} / ${model}` : '—'}</p>
        {!usable ? <Alert type="warning" showIcon message="目前没有足够的资料内容生成准确配图。" style={{ marginBottom: 12 }} /> : null}

        <div style={{ display: 'grid', gridTemplateColumns: uiPhase === 'done' ? '1fr 1fr' : '1fr', gap: 16 }}>
          <section>
            <Text strong>当前封面</Text>
            {currentCoverUrl && !currentPreviewBroken ? (
              <img
                src={currentCoverUrl}
                alt="当前封面"
                style={{ display: 'block', width: '100%', marginTop: 8, borderRadius: 8, maxHeight: 280, objectFit: 'contain' }}
                onError={() => setCurrentPreviewBroken(true)}
              />
            ) : <Paragraph type="secondary">{currentPreviewBroken ? '当前封面暂时无法预览' : '暂无当前封面'}</Paragraph>}
          </section>
          {uiPhase === 'done' && candidateCoverUrl ? (
            <section>
              <Text strong>新生成的候选封面</Text>
              {!candidatePreviewBroken ? (
                <img
                  src={candidateCoverUrl}
                  alt="候选封面"
                  style={{ display: 'block', width: '100%', marginTop: 8, borderRadius: 8, maxHeight: 280, objectFit: 'contain' }}
                  onLoad={() => setCandidatePreviewLoaded(true)}
                  onError={() => setCandidatePreviewBroken(true)}
                />
              ) : <Alert type="error" showIcon message="候选封面无法预览，当前封面未更改。" />}
              <Paragraph type="secondary" style={{ marginTop: 8 }}>请检查主体辨识度、对比度和与资料主题的匹配度，再决定是否使用。</Paragraph>
            </section>
          ) : null}
        </div>

        {uiPhase !== 'done' ? (
          <>
            <label style={{ display: 'block', marginBottom: 12 }}>
              <Text>色彩方案</Text>
              <Select
                aria-label="色彩方案"
                value={colorScheme}
                onChange={(value) => void changeColorScheme(value)}
                disabled={loading || uiPhase === 'running'}
                style={{ display: 'block', marginTop: 8, width: '100%' }}
                options={[
                  { value: 'auto', label: '自动（按主题与近期封面分布）' },
                  { value: 'cool', label: '冷色' },
                  { value: 'neutral', label: '中性' },
                  { value: 'warm', label: '暖色' },
                  { value: 'high_contrast', label: '高对比' },
                  { value: 'low_saturation', label: '低饱和' },
                  { value: 'vivid', label: '鲜艳' },
                ]}
              />
            </label>
            <label>
              <Text>提示词预览（可编辑，即实际发送内容）</Text>
              <Input.TextArea
                rows={5}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                style={{ marginTop: 8 }}
                disabled={loading || uiPhase === 'running'}
              />
            </label>
            <Paragraph type={tooLong ? 'danger' : 'secondary'} style={{ marginTop: 8, marginBottom: 0 }}>
              {charCount} / {maxChars} 字符{tooLong ? '（超出上限，请精简后再提交）' : ''}
            </Paragraph>
          </>
        ) : null}
        {uiPhase === 'running' ? <Alert type="info" showIcon message={stageLabel || '正在生成候选封面…'} style={{ marginTop: 12 }} /> : null}
        {uiPhase === 'failed' ? <Alert type="error" showIcon message={error || '生成失败；当前封面保持不变。'} style={{ marginTop: 12 }} /> : null}
        {uiPhase === 'done' ? <Alert type="success" showIcon message="候选封面已保存，当前封面尚未更改。" style={{ marginTop: 12 }} /> : null}
        {error && uiPhase !== 'failed' ? <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} /> : null}
      </Modal>
      <Modal
        title="确认再次生成封面？"
        open={confirmAgainOpen}
        okText="确认并再次生成"
        cancelText="取消"
        confirmLoading={loading}
        onCancel={() => setConfirmAgainOpen(false)}
        onOk={() => {
          setConfirmAgainOpen(false)
          setUiPhase('idle')
          submitGeneration()
        }}
      >
        <Alert
          type={budgetAvailable ? 'info' : 'warning'}
          showIcon
          message={budgetUsed !== null && monthlyBudget !== null ? `InsightHub 本地安全上限：${budgetUsed}/${monthlyBudget} 次` : '正在读取 InsightHub 本地安全上限'}
          description="再次确认后会新建一次 MiniMax 生图请求，可能消耗订阅额度。取消不会发起请求。"
        />
      </Modal>
    </>
  )
}
