import { Button, Typography } from 'antd'
import type { ReactNode } from 'react'

const { Text } = Typography

export type AppView = 'inbox' | 'library' | 'search' | 'ask' | 'briefs' | 'settings'

const NAV: Array<{ key: AppView; label: string }> = [
  { key: 'inbox', label: '收集' },
  { key: 'library', label: '知识库' },
  { key: 'search', label: '搜索' },
  { key: 'ask', label: '问答' },
  { key: 'briefs', label: '笔记' },
  { key: 'settings', label: '设置' },
]

type Props = {
  view: AppView
  onNavigate: (view: AppView) => void
  children: ReactNode
}

export function AppShell({ view, onNavigate, children }: Props) {
  return (
    <div className="app-shell">
      <nav className="app-nav" aria-label="主导航">
        <div className="app-nav-inner">
          <Text strong style={{ marginRight: 12, fontSize: 15 }}>InsightHub</Text>
          {NAV.map((item) => (
            <Button key={item.key} type={view === item.key ? 'link' : 'text'} className={view === item.key ? 'active' : ''} aria-label={item.label} onClick={() => onNavigate(item.key)}>
              {item.label}
            </Button>
          ))}
          <div className="app-legal-notice">
            <span>Copyright © InsightHub contributors · AGPL-3.0-only · 本软件不提供任何担保。</span>
            <a href="/LICENSE" target="_blank" rel="noreferrer">查看许可证</a>
            <a href="https://github.com/sabimonkey/InsightHub/tree/v1.0.0" target="_blank" rel="noreferrer">对应源代码</a>
          </div>
        </div>
      </nav>
      <div className="app-main">{children}</div>
    </div>
  )
}
