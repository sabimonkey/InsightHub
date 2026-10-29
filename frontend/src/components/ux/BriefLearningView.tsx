import { Button, Collapse, Typography } from 'antd'

const { Title, Paragraph, Text } = Typography

type LearningNote = {
  title: string
  highlights: string[]
  theme_notes: Array<{ title: string; summary: string; points: Array<{ text: string; label: string }> }>
  sections: Record<string, Array<{ text: string; label: string }>>
  follow_ups: string[]
}

type SourceIndex = {
  citation_number: number
  title: string
  original_url: string | null
  canonical_url: string | null
  filename: string | null
}

type Props = {
  learning: LearningNote | null | undefined
  sourceIndex: SourceIndex[]
  onOpenSource?: (citationNumber: number) => void
}

export function BriefLearningView({ learning, sourceIndex, onOpenSource }: Props) {
  if (!learning) {
    return <Paragraph type="secondary">暂无学习笔记内容。</Paragraph>
  }
  return (
    <div className="brief-learning">
      {learning.highlights.length ? (
        <section>
          <Title level={4}>本期重点</Title>
          <ul>{learning.highlights.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      ) : null}
      {learning.theme_notes.map((theme) => (
        <section key={theme.title}>
          <Title level={4}>主题笔记 · {theme.title}</Title>
          {theme.summary ? <Paragraph>{theme.summary}</Paragraph> : null}
          <ul>
            {theme.points.map((point) => (
              <li key={point.text}>
                <Text type="secondary">[{point.label}]</Text> {point.text}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {Object.entries(learning.sections).map(([heading, rows]) => (
        <section key={heading}>
          <Title level={4}>{heading}</Title>
          <ul>
            {rows.map((row) => (
              <li key={row.text}>
                <Text type="secondary">[{row.label}]</Text> {row.text}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {learning.follow_ups.length ? (
        <section>
          <Title level={4}>值得继续关注</Title>
          <ul>{learning.follow_ups.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      ) : null}
      <section>
        <Title level={4}>资料来源</Title>
        {sourceIndex.map((item) => (
          <Paragraph key={item.citation_number}>
            <Button type="link" size="small" onClick={() => onOpenSource?.(item.citation_number)}>[{item.citation_number}]</Button>
            {item.title} {item.canonical_url || item.original_url || item.filename || ''}
          </Paragraph>
        ))}
      </section>
      <Collapse
        size="small"
        items={[{ key: 'raw', label: '高级信息', children: <Paragraph type="secondary">技术字段与原始生成信息可在导出 Markdown 中查看。</Paragraph> }]}
      />
    </div>
  )
}
