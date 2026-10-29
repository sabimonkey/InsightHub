import { Alert, Button, Modal, Segmented, Space, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { fetchLibrary, fetchLibraryTrash, restoreSource, trashSource } from '../api'
import { KnowledgeCover } from '../components/ux/KnowledgeCover'
import { useSourceDetailPanel } from '../components/SourceDetailPanel'
import { PageHeader } from '../components/ux/PageHeader'
import { GenerateCoverModal } from '../components/ux/GenerateCoverModal'
import { SupplementTextModal } from '../components/ux/SupplementTextModal'
import { KnowledgeSourceCard, type KnowledgeCardItem } from '../components/ux/KnowledgeSourceCard'
import { EmptyState } from '../components/ux/EmptyState'

const { Text } = Typography

const SECTIONS = [
  { slug: 'all', label: '全部' },
  { slug: 'project_discovery', label: '发现项目' },
  { slug: 'business', label: '商业' },
  { slug: 'knowledge', label: '知识' },
  { slug: 'other', label: '其他' },
] as const

type LibraryItem = {
  source_id: string
  title?: string
  title_full?: string | null
  display_name: string
  source_type?: string
  categories: string[]
  last_collected_at?: string | null
  analysis_status?: string | null
  analysis_status_code?: string | null
  extraction_status_label?: string | null
  preview_image_url?: string | null
  cover_origin?: string | null
  collection_origin?: string
  supports_text_supplement?: boolean
}

type Props = {
  onOpenNote?: (sourceId: string) => void
  focusSourceId?: string | null
  onFocusHandled?: () => void
}

export function LibraryPage({ onOpenNote, focusSourceId, onFocusHandled }: Props) {
  const [section, setSection] = useState<string>('all')
  const [items, setItems] = useState<LibraryItem[]>([])
  const [focusMissing, setFocusMissing] = useState(false)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [coverSourceId, setCoverSourceId] = useState<string | null>(null)
  const [coverTitle, setCoverTitle] = useState<string | undefined>()
  const [supplementSourceId, setSupplementSourceId] = useState<string | null>(null)
  const [supplementTitle, setSupplementTitle] = useState<string | undefined>()
  const [view, setView] = useState<'library' | 'trash'>('library')
  const [trashItems, setTrashItems] = useState<Array<{
    source_id: string
    title: string
    categories: string[]
    first_collected_at?: string | null
    deleted_at: string
    days_until_purge_ui: number
    preview_image_url?: string | null
  }>>([])
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const focusApplied = useRef<string | null>(null)
  const { openDetail, panel: detailPanel } = useSourceDetailPanel({
    onError: (message) => setError(message),
  })

  function load(slug: string) {
    const params: { category?: string; scope: string } = { scope: 'mine' }
    if (slug !== 'all') params.category = slug
    void fetchLibrary(params).then((body) => setItems((body.items ?? []) as LibraryItem[]))
  }

  function loadTrash() {
    void fetchLibraryTrash()
      .then((body) => setTrashItems(body.items ?? []))
      .catch(() => message.error('无法加载最近删除'))
  }

  useEffect(() => {
    if (focusSourceId) {
      setSection('all')
      load('all')
      return
    }
    load(section)
  }, [focusSourceId])

  useEffect(() => {
    if (!focusSourceId) {
      focusApplied.current = null
      setFocusMissing(false)
      setHighlightId(null)
      return
    }
    if (focusApplied.current === focusSourceId) return
    const found = items.some((item) => item.source_id === focusSourceId)
    if (items.length === 0) return
    if (!found) {
      setFocusMissing(true)
      focusApplied.current = focusSourceId
      onFocusHandled?.()
      return
    }
    setFocusMissing(false)
    setHighlightId(focusSourceId)
    focusApplied.current = focusSourceId
    window.requestAnimationFrame(() => {
      const el = document.querySelector(`[data-source-id="${focusSourceId}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    const timer = window.setTimeout(() => {
      setHighlightId(null)
      onFocusHandled?.()
    }, 2400)
    return () => window.clearTimeout(timer)
  }, [focusSourceId, items, onFocusHandled])

  async function confirmTrash(sourceId: string) {
    try {
      await trashSource(sourceId)
      setItems((current) => current.filter((row) => row.source_id !== sourceId))
      message.success('已移至最近删除')
    } catch {
      message.error('删除失败')
    } finally {
      setPendingDeleteId(null)
    }
  }

  const cards: KnowledgeCardItem[] = items.map((item) => ({
    sourceId: item.source_id,
    title: item.title || item.display_name,
    titleFull: item.title_full,
    sourceType: item.source_type,
    collectedAt: item.last_collected_at,
    analysisStatus: item.analysis_status,
    analysisStatusCode: item.analysis_status_code,
    extractionStatusLabel: item.extraction_status_label,
    previewImageUrl: item.preview_image_url,
    coverOrigin: item.cover_origin,
    categories: item.categories,
    supportsTextSupplement: item.supports_text_supplement,
  }))

  return (
    <main className="app-page library-page">
      <PageHeader
        title={view === 'trash' ? '最近删除' : '知识库'}
        description={view === 'trash' ? '7 天内可恢复误删的资料。' : '浏览已经整理的资料，按分类快速回顾。'}
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        {view === 'library' ? (
          <Button onClick={() => { setView('trash'); loadTrash() }}>最近删除</Button>
        ) : (
          <Button onClick={() => setView('library')}>返回知识库</Button>
        )}
      </div>
      {error ? <Alert type="error" showIcon title={error} closable onClose={() => setError(null)} style={{ marginBottom: 16 }} /> : null}
      {focusMissing ? <Alert type="warning" showIcon title="未找到指定资料。" style={{ marginBottom: 16 }} /> : null}
      {view === 'library' ? (
        <>
          <Segmented
            options={SECTIONS.map((item) => ({ label: item.label, value: item.slug }))}
            value={section}
            onChange={(value) => {
              setSection(String(value))
              load(String(value))
            }}
          />
          <Space style={{ margin: '16px 0' }}>
            <Text type="secondary">按收藏时间排序（新到旧）</Text>
          </Space>
          {items.length === 0 ? <EmptyState title="知识库为空" hint="还没有资料。先去收集页面添加一个链接。" /> : null}
          <div className="knowledge-grid" data-testid="knowledge-grid">
            {cards.map((item) => (
              <KnowledgeSourceCard
                key={item.sourceId}
                item={item}
                highlighted={highlightId === item.sourceId}
                onOpen={(id) => onOpenNote?.(id)}
                onOpenDetail={openDetail}
                onDelete={(id) => setPendingDeleteId(id)}
                onGenerateCover={(id) => {
                  const row = items.find((item) => item.source_id === id)
                  setCoverTitle(row?.title || row?.display_name)
                  setCoverSourceId(id)
                }}
                onSupplement={(id) => {
                  const row = items.find((item) => item.source_id === id)
                  setSupplementTitle(row?.title || row?.display_name)
                  setSupplementSourceId(id)
                }}
              />
            ))}
          </div>
        </>
      ) : (
        <>
          {trashItems.length === 0 ? <EmptyState title="最近删除为空" hint="没有可恢复的资料。" /> : null}
          <div className="knowledge-grid" data-testid="library-trash-grid">
            {trashItems.map((item) => (
              <article key={item.source_id} className="knowledge-card" data-source-id={item.source_id}>
                <div className="knowledge-card-media">
                  <KnowledgeCover
                    sourceId={item.source_id}
                    previewImageUrl={item.preview_image_url}
                    title={item.title}
                    categories={item.categories}
                  />
                </div>
                <div className="knowledge-card-body">
                  <Text strong className="knowledge-card-title">{item.title}</Text>
                  <Text type="secondary" className="knowledge-card-meta">
                    删除于 {new Date(item.deleted_at).toLocaleDateString()} · 剩余 {item.days_until_purge_ui} 天
                  </Text>
                  <div className="knowledge-card-actions">
                    <Button
                      size="small"
                      type="primary"
                      aria-label="恢复资料"
                      onClick={() => {
                        void restoreSource(item.source_id).then(() => {
                          message.success('已恢复')
                          loadTrash()
                          load(section)
                          setView('library')
                        })
                      }}
                    >
                      恢复
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      <Modal
        open={pendingDeleteId !== null}
        title="将资料移至最近删除？"
        okText="移至最近删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        onCancel={() => setPendingDeleteId(null)}
        onOk={() => pendingDeleteId && void confirmTrash(pendingDeleteId)}
      >
        该资料将从知识库中隐藏，并在最近删除中保留 7 天。期间可以恢复。
      </Modal>
      <GenerateCoverModal
        sourceId={coverSourceId}
        title={coverTitle}
        open={coverSourceId !== null}
        onClose={() => setCoverSourceId(null)}
        onDone={() => load(section)}
      />
      <SupplementTextModal
        sourceId={supplementSourceId}
        title={supplementTitle}
        open={supplementSourceId !== null}
        onClose={() => setSupplementSourceId(null)}
        onDone={() => load(section)}
      />
      {detailPanel}
    </main>
  )
}
