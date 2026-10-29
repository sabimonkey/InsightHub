import { Button, Drawer, Dropdown, Input, Modal, Spin, Typography, message } from 'antd'
import type { MenuProps } from 'antd'
import { clearAskSessions, deleteAskSession, fetchSystemStatus } from '../api'
import { useEffect, useMemo, useRef, useState } from 'react'
import { MarkdownBody } from '../components/ux/MarkdownBody'
import { ResearchNoteCard } from '../components/ux/ResearchNoteCard'

const { Text, Title, Paragraph } = Typography

type Citation = {
  citation_number: number
  content_chunk_id: string
  source_item_id: string
  quote_text: string | null
  source_title: string
  original_url: string | null
}

type Turn = {
  id: string
  question: string
  status: string
  answer_markdown: string | null
  excluded_sensitive_source_count: number
  error_code: string | null
  citations: Citation[]
}

type AskPhase = 'idle' | 'planning' | 'retrieving' | 'answering' | 'validating' | 'done' | 'failed'

type StreamSlice = {
  phase: AskPhase
  draft: string
  citationsLocked: boolean
  errorMessage?: string
}

type SessionRow = { id: string; title: string | null; updated_at?: string }

const SUGGESTIONS = [
  '总结我最近收藏的 Agent 相关资料',
  '这些资料对 AI Memory 的观点有什么不同？',
  '有哪些项目值得继续了解？',
]

function dayBucket(value?: string) {
  if (!value) return '更早'
  const date = new Date(value)
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startYesterday = new Date(startToday)
  startYesterday.setDate(startYesterday.getDate() - 1)
  const weekAgo = new Date(startToday)
  weekAgo.setDate(weekAgo.getDate() - 7)
  if (date >= startToday) return '今天'
  if (date >= startYesterday) return '昨天'
  if (date >= weekAgo) return '最近7天'
  return '更早'
}

export function AskPage({ onOpenNote }: { onOpenNote?: (sourceId: string) => void }) {
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [providerReady, setProviderReady] = useState(true)
  const [answerModel, setAnswerModel] = useState('—')
  const [streamByTurn, setStreamByTurn] = useState<Record<string, StreamSlice>>({})
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const eventSourcesRef = useRef<Map<string, EventSource>>(new Map())
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false)

  const phaseLabel: Record<AskPhase, string> = {
    idle: '',
    planning: '正在理解问题…',
    retrieving: '正在检索知识库…',
    answering: '正在生成回答…',
    validating: '正在核对引用与来源…',
    done: '',
    failed: '',
  }

  function applyFinalTurn(turn: Turn) {
    setTurns((current) => current.map((item) => (item.id === turn.id ? turn : item)))
    setStreamByTurn((current) => ({
      ...current,
      [turn.id]: { phase: turn.status === 'FAILED' ? 'failed' : 'done', draft: '', citationsLocked: false },
    }))
  }

  function subscribeTurnEvents(turnId: string) {
    if (eventSourcesRef.current.has(turnId)) return
    const source = new EventSource(`/api/ask/turns/${turnId}/events`)
    eventSourcesRef.current.set(turnId, source)
    source.addEventListener('planning', () => {
      setStreamByTurn((current) => ({
        ...current,
        [turnId]: { ...(current[turnId] ?? { draft: '', citationsLocked: true }), phase: 'planning' },
      }))
    })
    source.addEventListener('retrieving', () => {
      setStreamByTurn((current) => ({
        ...current,
        [turnId]: { ...(current[turnId] ?? { draft: '', citationsLocked: true }), phase: 'retrieving' },
      }))
    })
    source.addEventListener('answer_started', () => {
      setStreamByTurn((current) => ({
        ...current,
        [turnId]: { ...(current[turnId] ?? { draft: '', citationsLocked: true }), phase: 'answering' },
      }))
    })
    source.addEventListener('delta', (event) => {
      try {
        const body = JSON.parse(event.data) as { text?: string }
        const piece = body.text ?? ''
        if (!piece) return
        setStreamByTurn((current) => {
          const prev = current[turnId] ?? { phase: 'answering', draft: '', citationsLocked: true }
          return {
            ...current,
            [turnId]: { ...prev, phase: 'answering', draft: `${prev.draft}${piece}` },
          }
        })
      } catch {
        /* ignore malformed transport payloads */
      }
    })
    source.addEventListener('validating', () => {
      setStreamByTurn((current) => ({
        ...current,
        [turnId]: { ...(current[turnId] ?? { draft: '', citationsLocked: true }), phase: 'validating' },
      }))
    })
    source.addEventListener('final', (event) => {
      try {
        const body = JSON.parse(event.data) as {
          status: string
          answer_markdown: string | null
          error_code: string | null
          citations: Citation[]
        }
        setTurns((current) =>
          current.map((row) =>
            row.id === turnId
              ? {
                  ...row,
                  status: body.status,
                  answer_markdown: body.answer_markdown,
                  error_code: body.error_code,
                  citations: body.citations ?? [],
                }
              : row,
          ),
        )
        setStreamByTurn((current) => ({
          ...current,
          [turnId]: { phase: body.status === 'FAILED' ? 'failed' : 'done', draft: '', citationsLocked: false },
        }))
      } finally {
        source.close()
        eventSourcesRef.current.delete(turnId)
      }
    })
    source.addEventListener('error', (event) => {
      if (!(event instanceof MessageEvent) || !event.data) return
      try {
        const body = JSON.parse(event.data) as { code?: string; message?: string }
        setTurns((current) =>
          current.map((row) =>
            row.id === turnId
              ? { ...row, status: 'FAILED', error_code: body.code ?? 'FAILED', answer_markdown: null, citations: [] }
              : row,
          ),
        )
        setStreamByTurn((current) => ({
          ...current,
          [turnId]: { phase: 'failed', draft: '', citationsLocked: false },
        }))
      } finally {
        source.close()
        eventSourcesRef.current.delete(turnId)
      }
    })
    source.onerror = () => {
      void fetch(`/api/ask/turns/${turnId}`)
        .then(async (response) => {
          if (!response.ok) return
          const polled = (await response.json()) as Turn
          if (polled.status !== 'PENDING' && polled.status !== 'RUNNING') applyFinalTurn(polled)
        })
        .catch(() => undefined)
    }
  }

  useEffect(() => {
    const sources = eventSourcesRef.current
    return () => {
      for (const source of sources.values()) source.close()
      sources.clear()
    }
  }, [])

  async function refreshSessions() {
    const response = await fetch('/api/ask/sessions')
    if (response.ok) {
      const body = (await response.json()) as { sessions: SessionRow[] }
      setSessions(body.sessions)
    }
  }

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  useEffect(() => {
    void refreshSessions()
    void fetch('/api/llm/providers')
      .then(async (response) => {
        if (!response.ok) return
        const body = (await response.json()) as Array<{ configured?: boolean }>
        if (Array.isArray(body)) setProviderReady(body.some((item) => item.configured))
      })
      .catch(() => undefined)
    void fetch('/api/llm/routes')
      .then(async (response) => {
        if (!response.ok) return
        const body = (await response.json()) as { routes: Array<{ workflow: string; deployment_display_name?: string; model?: string }> }
        const answer = body.routes.find((row) => row.workflow === 'ASK_ANSWER')
        setAnswerModel(answer?.deployment_display_name || answer?.model || '—')
      })
      .catch(() => setAnswerModel('—'))
  }, [])

  const grouped = useMemo(() => {
    const map = new Map<string, SessionRow[]>()
    for (const row of sessions) {
      const bucket = dayBucket(row.updated_at)
      map.set(bucket, [...(map.get(bucket) ?? []), row])
    }
    return map
  }, [sessions])

  async function openSession(id: string) {
    setSessionId(id)
    setHistoryDrawerOpen(false)
    const response = await fetch(`/api/ask/sessions/${id}`)
    if (response.ok) {
      const body = (await response.json()) as { turns: Turn[] }
      setTurns(body.turns)
      for (const row of body.turns) {
        if (row.status === 'PENDING' || row.status === 'RUNNING') subscribeTurnEvents(row.id)
      }
    }
  }

  function startNewSession() {
    setSessionId(null)
    setTurns([])
    setQuestion('')
  }

  async function sendQuestion(text: string) {
    const trimmed = text.trim()
    if (!trimmed || sending || !providerReady) return
    setSending(true)
    let id = sessionId
    try {
      if (!id) {
        const created = await fetch('/api/ask/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        })
        if (!created.ok) throw new Error('无法创建会话')
        id = ((await created.json()) as { id: string }).id
        setSessionId(id)
        await refreshSessions()
      }
      const response = await fetch(`/api/ask/sessions/${id}/turns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, filters: { scope: 'mine' } }),
      })
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: { message?: string; code?: string }; message?: string }
        const detail = body.detail
        throw new Error(detail?.message || body.message || detail?.code || '提问失败')
      }
      let turn = (await response.json()) as Turn
      setTurns((current) => [...current.filter((item) => item.id !== turn.id), turn])
      setStreamByTurn((current) => ({
        ...current,
        [turn.id]: { phase: 'planning', draft: '', citationsLocked: true },
      }))
      setQuestion('')
      await refreshSessions()
      subscribeTurnEvents(turn.id)
      for (let attempt = 0; attempt < 120 && (turn.status === 'PENDING' || turn.status === 'RUNNING'); attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500))
        const polled = await fetch(`/api/ask/turns/${turn.id}`)
        if (polled.ok) {
          turn = (await polled.json()) as Turn
          if (turn.status !== 'PENDING' && turn.status !== 'RUNNING') {
            applyFinalTurn(turn)
            break
          }
        }
      }
      if (turn.status === 'PENDING' || turn.status === 'RUNNING') {
        const system = await fetchSystemStatus()
        const workerDown = system.worker === 'not_detected'
        setStreamByTurn((current) => ({
          ...current,
          [turn.id]: {
            ...(current[turn.id] ?? { draft: '', citationsLocked: true }),
            phase: 'failed',
            errorMessage: workerDown
              ? '后台 Worker 未运行，任务仍在队列中。请执行 scripts\\manage.ps1 start 后刷新或重试。'
              : '回答生成超时，请稍后刷新会话查看结果或重试。',
          },
        }))
        if (workerDown) message.error('后台 Worker 未运行，无法完成问答。')
      }
      await refreshSessions()
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    } catch (caught: unknown) {
      window.alert(caught instanceof Error ? caught.message : '提问失败')
    } finally {
      setSending(false)
    }
  }

  function renderAnswer(turn: Turn) {
    const parts = (turn.answer_markdown ?? '').split(/(\[\d+\])/g)
    return (
      <div className="ask-answer">
        <div className="ask-answer-body">
          {parts.map((part, index) => {
            const match = /^\[(\d+)\]$/.exec(part)
            if (match) {
              const citation = turn.citations.find((item) => item.citation_number === Number(match[1]))
              return (
                <Button key={`${turn.id}-${index}`} size="small" type="link" onClick={() => citation && onOpenNote?.(citation.source_item_id)}>
                  {part}
                </Button>
              )
            }
            if (!part.trim()) return null
            return <MarkdownBody key={`${turn.id}-md-${index}`} markdown={part} />
          })}
        </div>
        {turn.citations.length ? (
          <section className="ask-sources">
            <Title level={5}>参考资料</Title>
            {turn.citations.map((item) => (
              <ResearchNoteCard
                key={item.citation_number}
                item={{
                  sourceId: item.source_item_id,
                  title: item.source_title,
                  summarySnippet: item.quote_text,
                  originalUrl: item.original_url,
                }}
                onRead={(id) => onOpenNote?.(id)}
              />
            ))}
          </section>
        ) : null}
      </div>
    )
  }

  const welcome = turns.length === 0

  function renderHistoryGroups() {
    return ['今天', '昨天', '最近7天', '更早'].map((bucket) => {
      const rows = grouped.get(bucket) ?? []
      if (!rows.length) return null
      return (
        <div key={bucket} className="ask-history-group">
          <Text type="secondary">{bucket}</Text>
          {rows.map((item) => {
            const menu: MenuProps['items'] = [
              {
                key: 'delete',
                label: '删除对话',
                danger: true,
                onClick: () => {
                  Modal.confirm({
                    title: '删除这条对话？',
                    okText: '删除',
                    okButtonProps: { danger: true },
                    onOk: async () => {
                      await deleteAskSession(item.id)
                      setSessions((current) => current.filter((row) => row.id !== item.id))
                      if (sessionId === item.id) startNewSession()
                    },
                  })
                },
              },
            ]
            return (
              <div key={item.id} className="ask-history-row">
                <button type="button" className={`ask-history-item${sessionId === item.id ? ' active' : ''}`} title={item.title || ''} onClick={() => void openSession(item.id)}>
                  {item.title?.trim() || '新对话'}
                </button>
                <Dropdown menu={{ items: menu }} trigger={['click']}>
                  <Button type="text" size="small" aria-label="对话菜单">⋯</Button>
                </Dropdown>
              </div>
            )
          })}
        </div>
      )
    })
  }

  function renderSidebarChrome() {
    return (
      <>
        <div className="ask-sidebar-head">
                  <Button type="primary" block onClick={startNewSession} data-testid="ask-new-session">新对话</Button>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
            <Text type="secondary">对话历史</Text>
            <Button
              type="link"
              size="small"
              danger
              disabled={!sessions.length}
              onClick={() => {
                Modal.confirm({
                  title: '确定清空全部对话历史？',
                  content: `将隐藏 ${sessions.length} 条对话记录，不会删除知识库资料。`,
                  okText: '清空历史',
                  okButtonProps: { danger: true },
                  onOk: async () => {
                    await clearAskSessions()
                    setSessions([])
                    startNewSession()
                    message.success('已清空对话历史')
                  },
                })
              }}
            >
              清空历史
            </Button>
          </div>
        </div>
        <div className="ask-session-list" data-testid="ask-session-list">
          {renderHistoryGroups()}
        </div>
      </>
    )
  }

  const composerField = (
    <Input.TextArea
      className="ask-composer-input"
      aria-label="输入问题"
      value={question}
      onChange={(event) => setQuestion(event.target.value)}
      placeholder="输入你的问题…"
      autoSize={welcome ? false : { minRows: 2, maxRows: 6 }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault()
          void sendQuestion(question)
        }
      }}
    />
  )
  const composerSubmit = (
    <Button
      className="ask-composer-send"
      aria-label="提交问题"
      type="primary"
      loading={sending}
      disabled={!providerReady || !question.trim()}
      onClick={() => void sendQuestion(question)}
    >
      {providerReady ? '发送' : '模型未配置'}
    </Button>
  )
  const welcomeComposer = (
    <div className="ask-composer-shell ask-composer-shell--welcome">
      {composerField}
      {composerSubmit}
    </div>
  )
  const activeComposer = (
    <div className="ask-composer ask-composer-grid">
      {composerField}
      {composerSubmit}
    </div>
  )

  return (
    <section className="ask-workspace">
      <aside className="ask-sidebar ask-sidebar--desktop">{renderSidebarChrome()}</aside>
      <Drawer title="对话历史" placement="left" open={historyDrawerOpen} onClose={() => setHistoryDrawerOpen(false)} size={280} className="ask-history-drawer" destroyOnHidden>
        <div className="ask-sidebar ask-sidebar--drawer">{renderSidebarChrome()}</div>
      </Drawer>
      <div className="ask-main">
        <header className="ask-header">
          <Button type="default" className="ask-history-toggle" aria-label="打开对话历史" onClick={() => setHistoryDrawerOpen(true)}>
            历史
          </Button>
          <Title level={3} className="ask-page-title" style={{ margin: 0 }}>问答</Title>
          <Text type="secondary" className="ask-page-desc">基于知识库回答问题，并提供可追溯的资料来源。</Text>
          <Text type="secondary" className="ask-page-model">当前回答模型：{answerModel}</Text>
        </header>
        <div className="ask-body">
          {welcome ? (
            <div className="ask-empty-pane" data-testid="ask-empty-pane">
              <div className="ask-welcome">
                <Title level={4} className="ask-welcome-title">基于你的知识库提问</Title>
                <div className="ask-composer ask-composer--welcome">{welcomeComposer}</div>
                <div className="ask-suggestions">
                  {SUGGESTIONS.map((item) => (
                    <Button key={item} onClick={() => setQuestion(item)}>{item}</Button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="ask-thread" data-testid="ask-message-thread">
                {turns.map((turn) => (
            <article key={turn.id} className="ask-turn">
              <div className="ask-bubble ask-bubble-user">
                <Text strong>你</Text>
                <Paragraph style={{ marginBottom: 0 }}>{turn.question}</Paragraph>
              </div>
              <div className="ask-bubble ask-bubble-assistant">
                <Text strong>InsightHub</Text>
                {(() => {
                  const stream = streamByTurn[turn.id]
                  const active = turn.status === 'RUNNING' || turn.status === 'PENDING'
                  const phase = stream?.phase ?? (active ? 'planning' : 'idle')
                  const statusText = phaseLabel[phase]
                  if (phase === 'failed' && stream?.errorMessage) {
                    return <Paragraph type="danger">{stream.errorMessage}</Paragraph>
                  }
                  if (active && statusText) {
                    return <Paragraph type="secondary">{statusText}</Paragraph>
                  }
                  return null
                })()}
                {turn.status === 'RUNNING' || turn.status === 'PENDING' ? (
                  streamByTurn[turn.id]?.draft ? (
                    <div className="ask-answer ask-answer-draft">
                      <MarkdownBody markdown={streamByTurn[turn.id].draft} />
                      <Text type="secondary">生成中</Text>
                    </div>
                  ) : (
                    <Spin size="small" />
                  )
                ) : null}
                {turn.status === 'NO_EVIDENCE' ? <Paragraph>当前 InsightHub 中没有足够资料回答这个问题。</Paragraph> : null}
                {turn.excluded_sensitive_source_count > 0 ? (
                  <Paragraph type="secondary">已按隐私策略排除 {turn.excluded_sensitive_source_count} 条敏感来源。</Paragraph>
                ) : null}
                {(turn.status === 'SUCCEEDED' || turn.status === 'PARTIAL') ? renderAnswer(turn) : null}
                {turn.status === 'RUNNING' || turn.status === 'PENDING' ? (
                  <Paragraph type="secondary">引用将在生成完成后核验</Paragraph>
                ) : null}
                {turn.status === 'FAILED' ? <Paragraph type="danger">回答失败：{turn.error_code ?? '未知错误'}</Paragraph> : null}
              </div>
            </article>
                ))}
                <div ref={bottomRef} />
              </div>
              <footer className="ask-composer ask-composer--active" data-testid="ask-composer-active">
                {activeComposer}
              </footer>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
