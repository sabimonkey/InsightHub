import { Alert, Button, Card, Checkbox, Collapse, Input, Modal, Segmented, Space, Tag, Typography, message } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { useEffect, useMemo, useState } from 'react'
import { fetchSource } from '../api'
import { BriefLearningView } from '../components/ux/BriefLearningView'
import { SourceDetailDrawer } from '../components/SourceDetailDrawer'
import { useBriefWorkspace, type BriefRow } from '../hooks/useBriefWorkspace'
import type { SourceDetail } from '../types'

const { Title, Text, Paragraph } = Typography

function noteDisplayMessage(value: string | null | undefined, fallback: string) {
  return (value || fallback).replaceAll('简报', '笔记')
}

export function BriefPage({ onOpenNote: _onOpenNote }: { onOpenNote?: (sourceId: string) => void }) {
  const ws = useBriefWorkspace()
  const { patchDraft } = ws
  const [categoryOptions, setCategoryOptions] = useState<Array<{ id: string; name: string; slug: string }>>([])
  const [topicOptions, setTopicOptions] = useState<Array<{ id: string; name: string }>>([])
  const [selectedTopics, setSelectedTopics] = useState<Array<{ id: string; name: string }>>([])
  const [topicQuery, setTopicQuery] = useState('')
  const [sourceDetail, setSourceDetail] = useState<SourceDetail | null>(null)
  const [focusChunkId, setFocusChunkId] = useState<string | null>(null)
  const [historyMutationBusy, setHistoryMutationBusy] = useState(false)

  useEffect(() => {
    void fetch('/api/categories')
      .then(async (response) => {
        if (response.ok) setCategoryOptions((await response.json()) as Array<{ id: string; name: string; slug: string }>)
      })
      .catch(() => setCategoryOptions([]))
    void fetch('/api/topics')
      .then(async (response) => {
        if (response.ok) setTopicOptions((await response.json()) as Array<{ id: string; name: string }>)
      })
      .catch(() => setTopicOptions([]))
  }, [])

  useEffect(() => {
    patchDraft({ topic_ids: selectedTopics.map((item) => item.id) })
  }, [selectedTopics, patchDraft])

  const succeededBriefs = useMemo(
    () => ws.briefs.filter((item) => item.status === 'SUCCEEDED' || item.status === 'PARTIAL' || item.status === 'NO_CONTENT'),
    [ws.briefs],
  )
  const failedBriefs = useMemo(() => ws.briefs.filter((item) => item.status === 'FAILED'), [ws.briefs])
  const activeBriefs = useMemo(() => ws.briefs.filter((item) => item.status === 'PENDING' || item.status === 'RUNNING'), [ws.briefs])

  function basisLabel(basis: string) {
    return basis === 'PUBLISHED_AT' ? '来源日期' : '收藏日期'
  }

  function briefStatusLabel(status: string) {
    if (status === 'SUCCEEDED' || status === 'PARTIAL') return '已完成'
    if (status === 'FAILED') return '失败'
    if (status === 'PENDING') return '排队中'
    if (status === 'RUNNING') return '生成中'
    return status
  }

  function historyTitle(item: BriefRow) {
    if (item.learning_note?.title && item.learning_note.title !== '学习摘要') return item.learning_note.title
    return `${item.start_date} — ${item.end_date}`
  }

  async function onGenerate() {
    const result = await ws.generateNew()
    if (!result.ok) message.error(noteDisplayMessage(result.message, '无法启动学习笔记生成'))
    else if (result.brief.status === 'PENDING' || result.brief.status === 'RUNNING') {
      message.warning('生成仍在进行或超时，请稍后在历史中刷新查看。')
    }
  }

  async function copyBrief(markdown: string | null | undefined) {
    if (!markdown) return
    await navigator.clipboard.writeText(markdown)
    message.success('已复制')
  }

  function confirmDeleteBrief(item: BriefRow) {
    Modal.confirm({
      title: '删除这条学习笔记？',
      content: '只删除这条笔记历史及其正文，不会删除原始资料、分析或证据。',
      okText: '删除笔记',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setHistoryMutationBusy(true)
        try {
          await ws.deleteBrief(item.id)
          message.success('已删除学习笔记')
        } catch (error) {
          message.error(error instanceof Error ? error.message : '删除失败')
        } finally {
          setHistoryMutationBusy(false)
        }
      },
    })
  }

  function confirmClearHistory() {
    Modal.confirm({
      title: '清空学习笔记历史？',
      content: '将删除所有学习笔记历史及其正文，不会删除原始资料、知识库内容、分析或其他模块的历史记录。',
      okText: '清空历史',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setHistoryMutationBusy(true)
        try {
          await ws.clearBriefHistory()
          message.success('学习笔记历史已清空')
        } catch (error) {
          message.error(error instanceof Error ? error.message : '清空失败')
        } finally {
          setHistoryMutationBusy(false)
        }
      },
    })
  }

  function renderHistoryRow(item: BriefRow) {
    const slugs = item.filters?.category_slugs ?? []
    const scopeLabel = slugs.length === 1 ? slugs[0] : slugs.length ? `${slugs.length}类` : '全部分类'
    return (
      <div className="brief-history-row" key={item.id}>
        <button
          type="button"
          className={`brief-history-item${ws.sidebarActiveId === item.id ? ' active' : ''}`}
          aria-label={`history ${item.id}`}
          onClick={() => void ws.selectHistory(item)}
        >
          <Text strong>{historyTitle(item)}</Text>
          <Text type="secondary">
            {scopeLabel} · {item.included_source_count} 条 · {briefStatusLabel(item.status)}
          </Text>
        </button>
        <Button
          type="text"
          className="brief-history-delete"
          aria-label={`删除学习笔记 ${historyTitle(item)}`}
          title="删除学习笔记"
          disabled={historyMutationBusy || item.status === 'PENDING' || item.status === 'RUNNING'}
          icon={<DeleteOutlined />}
          onClick={() => confirmDeleteBrief(item)}
        />
      </div>
    )
  }

  const readingBrief =
    ws.reading.mode === 'history' ? ws.reading.brief : ws.reading.mode === 'generation' ? ws.reading.brief : null

  const visibleTopics = topicOptions.filter((item) => item.name.toLowerCase().includes(topicQuery.trim().toLowerCase()))
  const generationActive = ws.reading.mode === 'generation' && (ws.reading.polling || ws.reading.brief?.status === 'PENDING' || ws.reading.brief?.status === 'RUNNING')

  return (
    <section className="brief-workspace">
      <aside className="brief-sidebar">
        <div className="brief-history-heading">
          <Title level={4}>学习笔记历史</Title>
          {ws.briefs.length ? <Button type="text" danger disabled={historyMutationBusy || activeBriefs.length > 0} onClick={confirmClearHistory}>清空历史</Button> : null}
        </div>
        {activeBriefs.map((item) => renderHistoryRow(item))}
        {succeededBriefs.map((item) => renderHistoryRow(item))}
        {!ws.briefs.length ? <Text type="secondary">暂无学习笔记历史</Text> : null}
        {failedBriefs.length ? (
          <Collapse
            size="small"
            items={[{
              key: 'failed',
              label: `失败记录 (${failedBriefs.length})`,
              children: failedBriefs.map((item) => renderHistoryRow(item)),
            }]}
          />
        ) : null}
      </aside>
      <div className="brief-main">
        <Title level={2}>笔记</Title>
        <Paragraph>把一段时间内的资料综合成可阅读的学习笔记。</Paragraph>
        <Card title="新建学习笔记" className="brief-config-card">
          <div className="brief-config-grid" aria-label="brief draft config">
          <section className="brief-config-section" aria-label="时间范围">
            <Text strong className="brief-config-section-title">时间范围</Text>
            <div className="brief-date-row">
              <label>
                开始日期
                <Input
                  aria-label="brief start"
                  value={ws.draft.start_date}
                  onChange={(event) => ws.patchDraft({ start_date: event.target.value, activePreset: null })}
                />
              </label>
              <label>
                结束日期
                <Input
                  aria-label="brief end"
                  value={ws.draft.end_date}
                  onChange={(event) => ws.patchDraft({ end_date: event.target.value, activePreset: null })}
                />
              </label>
            </div>
            <div className="brief-preset-row">
              {([
                ['today', '今天'],
                ['yesterday', '昨天'],
                ['last7', '最近7天'],
                ['thisWeek', '本周'],
                ['lastWeek', '上周'],
                ['thisMonth', '本月'],
                ['lastMonth', '上月'],
              ] as const).map(([preset, label]) => (
                <Button
                  key={preset}
                  className={ws.draft.activePreset === preset ? 'brief-preset-selected' : 'brief-preset-option'}
                  type="default"
                  aria-pressed={ws.draft.activePreset === preset}
                  aria-label={`preset ${preset === 'thisWeek' ? 'this week' : preset === 'lastWeek' ? 'last week' : preset === 'thisMonth' ? 'this month' : preset === 'lastMonth' ? 'last month' : preset}`}
                  onClick={() => ws.applyPreset(preset)}
                >
                  {label}
                </Button>
              ))}
            </div>
            <select
              aria-label="date basis"
              value={ws.draft.date_basis}
              onChange={(event) => ws.patchDraft({ date_basis: event.target.value })}
              style={{ marginTop: 12 }}
            >
              <option value="COLLECTED_AT">按收藏日期</option>
              <option value="PUBLISHED_AT">按发布日期</option>
            </select>
          </section>
          <section className="brief-config-section" aria-label="资料范围">
            <Text strong className="brief-config-section-title">资料范围</Text>
            <Checkbox aria-label="all categories" checked={ws.draft.category_slugs.length === 0} onChange={() => ws.patchDraft({ category_slugs: [] })}>
              全部
            </Checkbox>
            <Checkbox.Group
              style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}
              value={ws.draft.category_slugs}
              options={categoryOptions.map((item) => ({ label: item.name, value: item.slug }))}
              onChange={(values) => ws.patchDraft({ category_slugs: values as string[] })}
            />
          </section>
          <section className="brief-config-section" aria-label="主题与生成设置">
            <Text strong className="brief-config-section-title">主题与生成设置</Text>
            <Text type="secondary">自定义关注主题（可选）</Text>
            <Input aria-label="topic search" placeholder="搜索主题标签" value={topicQuery} onChange={(event) => setTopicQuery(event.target.value)} style={{ marginTop: 8 }} />
            <Space wrap style={{ marginTop: 8 }}>
              {visibleTopics.slice(0, 8).map((item) => {
                const selected = selectedTopics.some((topic) => topic.id === item.id)
                return <Button
                  key={item.id}
                  className={`brief-topic-chip${selected ? ' selected' : ''}`}
                  aria-pressed={selected}
                  onClick={() => setSelectedTopics((currentTopics) => selected
                    ? currentTopics.filter((topic) => topic.id !== item.id)
                    : [...currentTopics, item])}
                >
                  {item.name}
                </Button>
              })}
            </Space>
            <Segmented
              aria-label="detail level"
              className="brief-detail-segmented"
              value={ws.draft.detail_level}
              options={[
                { label: '极简', value: 'CONCISE' },
                { label: '标准', value: 'STANDARD' },
                { label: '详细', value: 'DETAILED' },
              ]}
              onChange={(value) => ws.patchDraft({ detail_level: String(value) })}
            />
            <Space style={{ marginTop: 16 }}>
              <Button onClick={() => void ws.runPreview()}>预览资料</Button>
              <Button type="primary" disabled={!ws.providerReady || generationActive} onClick={() => void onGenerate()}>
                {!ws.providerReady ? '模型未配置' : generationActive ? '正在生成…' : '生成学习笔记'}
              </Button>
            </Space>
          </section>
          <section className="brief-config-section" aria-label="资料预览">
            <Text strong className="brief-config-section-title">资料预览</Text>
            {ws.previewDiagnosis ? <Paragraph>{noteDisplayMessage(ws.previewDiagnosis.message, '')}</Paragraph> : <Paragraph type="secondary">点击「预览资料」查看候选统计。</Paragraph>}
            {ws.previewStats ? (
              <Paragraph type="secondary">
                范围内 {ws.previewStats.total_in_range} 条 · 正文可用 {ws.previewStats.extraction_ready_count ?? '—'} · 分析完成 {ws.previewStats.analysis_ready_count ?? '—'} · 可生成{' '}
                {ws.previewStats.included_for_brief} 条
                {ws.previewStats.extraction_ready_count != null &&
                ws.previewStats.analysis_ready_count != null &&
                ws.previewStats.extraction_ready_count > ws.previewStats.analysis_ready_count ? (
                  <span>（部分资料需先完成 AI 分析，见 RULE-016）</span>
                ) : null}
              </Paragraph>
            ) : null}
            <div className="brief-preview-list">
              {ws.preview.map((item) => (
                <div key={item.source_id}>
                  <Text>{item.title}</Text>
                  <Text type="secondary"> · {item.included ? '可生成' : item.exclusion_reason || '不可用'}</Text>
                </div>
              ))}
            </div>
          </section>
          </div>
        </Card>

        <div className="brief-result-area">
        {ws.reading.mode === 'idle' ? <Paragraph type="secondary">选择历史笔记，或使用上方配置生成新的学习笔记。</Paragraph> : null}

        {ws.reading.mode === 'history' && ws.draftDiffersFromHistory ? (
          <Alert
            type="info"
            showIcon
            title="上方「新建学习笔记」的日期与当前历史笔记不同"
            description="阅读区展示的是历史笔记；预览与「生成学习笔记」仅使用上方新建配置，不会改写历史记录。"
          />
        ) : null}

        {ws.reading.mode === 'generation' && ws.reading.polling ? (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 16 }}
            title={ws.reading.brief?.status === 'PENDING' ? '学习笔记正在排队' : '正在生成学习笔记…'}
            description={<Space direction="vertical"><span>{ws.reading.configSnapshot.start_date} — {ws.reading.configSnapshot.end_date} · 任务 {ws.reading.brief?.id ?? '正在创建'}</span>{ws.reading.statusCheckFailed ? <span>状态查询暂时失败，系统会继续检查该任务。</span> : null}</Space>}
          />
        ) : null}
        {ws.reading.mode === 'generation' && !ws.reading.polling && ws.reading.brief && (ws.reading.brief.status === 'PENDING' || ws.reading.brief.status === 'RUNNING') ? (
          <Alert type="warning" showIcon title="任务仍在后台运行，状态轮询已暂停" description={`任务 ID：${ws.reading.brief.id}`} action={<Button onClick={() => void ws.resumePolling()}>继续检查</Button>} />
        ) : null}

        {readingBrief ? (
          <article className="brief-article" ref={ws.readingRef} aria-label="brief reading surface">
            <header className="brief-article-header">
              <Space wrap style={{ marginBottom: 8 }}>
                {ws.reading.mode === 'history' ? <Tag aria-label="reading context history">正在阅读：历史笔记</Tag> : null}
                {ws.reading.mode === 'generation' && !ws.reading.polling ? (
                  <Tag color="green" aria-label="reading context generation">
                    最新生成结果
                  </Tag>
                ) : null}
                {ws.reading.mode === 'generation' && ws.reading.polling ? <Tag aria-label="reading context generating">生成中</Tag> : null}
              </Space>
              <Title level={3}>{readingBrief.learning_note?.title || `${readingBrief.end_date} · 学习笔记`}</Title>
              <Paragraph type="secondary">
                根据 {readingBrief.start_date} — {readingBrief.end_date}（{basisLabel(readingBrief.date_basis ?? ws.draft.date_basis)}）的 {readingBrief.included_source_count}{' '}
                条资料生成
              </Paragraph>
              <Space wrap>
                <Button onClick={() => void copyBrief(readingBrief.content_markdown)}>复制</Button>
                <a href={`/api/briefs/${readingBrief.id}/export?format=markdown`}>Markdown</a>
                <a href={`/api/briefs/${readingBrief.id}/export?format=pdf`}>PDF</a>
                <a href={`/api/briefs/${readingBrief.id}/export?format=docx`}>DOCX</a>
                <Button aria-label="regenerate history brief" disabled={readingBrief.status === 'PENDING' || readingBrief.status === 'RUNNING'} onClick={() => void ws.regenerateReading()}>
                  重新生成
                </Button>
              </Space>
            </header>
            {ws.reading.mode === 'history' && ws.reading.loading ? <Paragraph type="secondary">正在加载历史笔记…</Paragraph> : null}
            {(readingBrief.status === 'PENDING' || readingBrief.status === 'RUNNING') && ws.reading.mode === 'generation' ? (
              <Paragraph type="secondary">正在生成学习笔记…（任务 ID：{readingBrief.id}）</Paragraph>
            ) : null}
            {readingBrief.status === 'FAILED' || readingBrief.error_code === 'WORKER_NOT_CONSUMING' ? (
              <Paragraph type="danger">{noteDisplayMessage(readingBrief.error_message, readingBrief.error_code || '生成失败')}</Paragraph>
            ) : null}
            {readingBrief.status === 'NO_CONTENT' ? <Paragraph>{noteDisplayMessage(readingBrief.error_message, '该时间范围内没有可生成笔记的资料。')}</Paragraph> : null}
            {readingBrief.error_code === 'BRIEF_PRIVACY_PROVIDER_NOT_ALLOWED' ? <Paragraph>{noteDisplayMessage(readingBrief.error_message, '')}</Paragraph> : null}
            <BriefLearningView
              learning={readingBrief.learning_note}
              sourceIndex={readingBrief.source_index}
              onOpenSource={(number) => {
                const citation = readingBrief.citations.find((item) => item.citation_number === number)
                if (!citation) return
                setFocusChunkId(citation.content_chunk_id)
                void fetchSource(citation.source_item_id).then(setSourceDetail)
              }}
            />
          </article>
        ) : null}
        </div>
      </div>
      <SourceDetailDrawer open={sourceDetail !== null} detail={sourceDetail} discovery={null} analysis={null} focusChunkId={focusChunkId} onClose={() => setSourceDetail(null)} />
    </section>
  )
}
