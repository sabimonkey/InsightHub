import ReactMarkdown from 'react-markdown'

type Props = {
  markdown: string
  className?: string
}

export function MarkdownBody({ markdown, className }: Props) {
  return (
    <div className={className ?? 'markdown-body'}>
      <ReactMarkdown
        allowedElements={['p', 'strong', 'em', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'code', 'pre', 'a']}
        unwrapDisallowed
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
}
