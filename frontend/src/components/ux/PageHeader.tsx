import type { ReactNode } from 'react'
import { Typography } from 'antd'

const { Title, Paragraph } = Typography

export function PageHeader({ title, description, extra }: { title: string; description?: string; extra?: ReactNode }) {
  return (
    <header className="page-header" style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
      <div>
        <Title level={2} className="page-title">{title}</Title>
        {description ? <Paragraph className="page-desc" style={{ marginBottom: 0 }}>{description}</Paragraph> : null}
      </div>
      {extra ? <div>{extra}</div> : null}
    </header>
  )
}
