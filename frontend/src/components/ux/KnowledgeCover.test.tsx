import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { KnowledgeCover } from './KnowledgeCover'

afterEach(() => cleanup())

describe('KnowledgeCover', () => {
  it('shows themed cover when no preview url', () => {
    render(<KnowledgeCover sourceId="src-1" sourceType="TEXT" categories={[]} title="Note" />)
    expect(screen.getByTestId('knowledge-themed-cover')).toBeInTheDocument()
  })

  it('uses an explicit placeholder when only metadata is available', () => {
    render(
      <KnowledgeCover
        sourceId="src-x"
        coverOrigin="content_incomplete"
        sourceType="URL"
        categories={[]}
        title="A title derived from metadata"
      />,
    )
    expect(screen.getByText('正文待补充')).toBeInTheDocument()
    expect(screen.queryByText('AI 配图')).not.toBeInTheDocument()
  })

  it('shows image when preview url provided', () => {
    render(
      <KnowledgeCover
        sourceId="src-2"
        previewImageUrl="/api/sources/x/cover-image"
        sourceType="URL"
        categories={['knowledge']}
      />,
    )
    expect(document.querySelector('.knowledge-cover--photo img')).toHaveAttribute('src', '/api/sources/x/cover-image')
  })
})
