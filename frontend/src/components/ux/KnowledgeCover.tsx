import { useState } from 'react'
import { resolveCoverTheme } from '../../lib/themedCover'

type Props = {
  sourceId: string
  previewImageUrl?: string | null
  coverOrigin?: string | null
  sourceType?: string | null
  categories?: string[]
  title?: string
}

export function KnowledgeCover({ sourceId, previewImageUrl, coverOrigin, sourceType, categories, title }: Props) {
  const [failed, setFailed] = useState(false)
  const { theme, variant } = resolveCoverTheme(sourceId, categories, sourceType)
  const showRemote = Boolean(previewImageUrl) && !failed

  if (showRemote) {
    return (
      <div className="knowledge-cover knowledge-cover--photo">
        {coverOrigin === 'generated' ? <span className="knowledge-cover-ai-badge">AI 配图</span> : null}
        <img
          key={previewImageUrl}
          src={previewImageUrl!}
          alt=""
          loading="lazy"
          decoding="async"
          className="knowledge-card-image"
          onError={() => setFailed(true)}
        />
      </div>
    )
  }

  return (
    <div
      className={`knowledge-cover knowledge-cover--themed knowledge-cover--${theme} knowledge-cover--v${variant}`}
      aria-hidden
      data-testid="knowledge-themed-cover"
    >
      <div className="knowledge-cover-shape knowledge-cover-shape-a" />
      <div className="knowledge-cover-shape knowledge-cover-shape-b" />
      <span className="knowledge-cover-label">
        {coverOrigin === 'content_incomplete' ? '正文待补充' : title?.slice(0, 24) || themeLabel(theme)}
      </span>
    </div>
  )
}

function themeLabel(theme: string): string {
  const labels: Record<string, string> = {
    knowledge: '知识',
    business: '商业',
    project_discovery: '项目',
    url: '网页',
    text: '文本',
    file: '文件',
    github: 'GitHub',
    x: 'X',
    default: '资料',
  }
  return labels[theme] ?? '资料'
}
