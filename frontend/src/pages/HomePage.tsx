import { Typography } from 'antd'

const { Title, Paragraph } = Typography

export function HomePage() {
  return (
    <main style={{ maxWidth: 720, margin: '72px auto', padding: '0 24px' }}>
      <Title level={1}>InsightHub</Title>
      <Paragraph>Personal Research & Learning Intelligence Hub</Paragraph>
      <Paragraph>System Foundation Ready</Paragraph>
    </main>
  )
}
