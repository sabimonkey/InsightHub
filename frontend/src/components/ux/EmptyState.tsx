import { Typography } from 'antd'

const { Paragraph } = Typography

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <section aria-label="empty state" style={{ padding: '32px 0', textAlign: 'center' }}>
      <Paragraph strong>{title}</Paragraph>
      {hint ? <Paragraph type="secondary">{hint}</Paragraph> : null}
    </section>
  )
}
