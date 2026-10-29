import { Button, Collapse, Input, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { PageHeader } from '../components/ux/PageHeader'
import { ResearchNoteCard } from '../components/ux/ResearchNoteCard'
import { EmptyState } from '../components/ux/EmptyState'

type SearchResult = {
  source_id: string
  chunk_id: string
  source_title: string
  source_type: string
  snippet: string
  retrieval_methods: string[]
  category: string[]
  topics: string[]
  original_url: string | null
}

type IndexStatus = {
  configured: boolean
  semantic_available: boolean
  indexed_chunks: number
  total_current_chunks: number
  backfill_status: string | null
}

export function SearchPage({ onOpenNote }: { onOpenNote?: (sourceId: string) => void }) {
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState('mine')
  const [category, setCategory] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [status, setStatus] = useState<IndexStatus | null>(null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)

  async function loadStatus() {
    const response = await fetch('/api/index/status')
    if (response.ok) {
      setStatus((await response.json()) as IndexStatus)
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  async function runSearch() {
    setSearching(true)
    const response = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        mode,
        filters: { scope, ...(category ? { category } : {}) },
      }),
    })
    setSearching(false)
    if (!response.ok) {
      return
    }
    const body = (await response.json()) as { results: SearchResult[] }
    setResults(body.results)
  }

  const indexed = status ? `${status.indexed_chunks} / ${status.total_current_chunks} 条已索引` : ''

  return (
    <main className="app-page app-page--standard">
      <PageHeader title="搜索" description="搜索自己的知识库。默认使用智能搜索（关键词 + 语义）。 " />
      <Input.Search
        aria-label="搜索"
        size="large"
        placeholder="搜索资料、主题，或直接输入一句自然语言……"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onSearch={() => void runSearch()}
        loading={searching}
        enterButton="搜索"
      />
      <Space style={{ margin: '12px 0' }}>
        <Typography.Text type="secondary">知识库索引：{indexed || '加载中…'}</Typography.Text>
        <Button size="small" onClick={() => void fetch('/api/index/backfill', { method: 'POST' }).then(() => loadStatus())}>补建索引</Button>
      </Space>
      <Collapse
        size="small"
        items={[
          {
            key: 'advanced',
            label: '高级搜索',
            children: (
              <Space wrap>
                <select aria-label="范围" value={scope} onChange={(event) => setScope(event.target.value)}>
                  <option value="mine">我的收藏</option>
                  <option value="all">全部</option>
                  <option value="discovered">系统发现</option>
                </select>
                <select aria-label="分类" value={category} onChange={(event) => setCategory(event.target.value)}>
                  <option value="">全部分类</option>
                  <option value="knowledge">知识</option>
                  <option value="business">商业</option>
                </select>
                <select aria-label="模式" value={mode} onChange={(event) => setMode(event.target.value)}>
                  <option value="hybrid">智能（混合）</option>
                  <option value="keyword">关键词</option>
                </select>
              </Space>
            ),
          },
        ]}
      />
      {results.length === 0 && query ? <EmptyState title="没有找到相关资料" hint="可以尝试换一种表达。" /> : null}
      {results.map((item) => (
        <ResearchNoteCard
          key={`${item.source_id}-${item.chunk_id}`}
          item={{
            sourceId: item.source_id,
            title: item.source_title,
            sourceType: item.source_type,
            summarySnippet: item.snippet,
            originalUrl: item.original_url,
            topics: item.topics,
          }}
          onRead={(id) => onOpenNote?.(id)}
        />
      ))}
    </main>
  )
}
