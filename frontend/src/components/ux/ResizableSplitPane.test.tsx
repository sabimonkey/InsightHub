import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { COLLECTION_SPLIT_STORAGE_KEY, DEFAULT_COLLECTION_SPLIT_RATIO } from '../../lib/collectionSplit'
import { ResizableSplitPane } from './ResizableSplitPane'

afterEach(() => {
  cleanup()
  localStorage.removeItem(COLLECTION_SPLIT_STORAGE_KEY)
})

describe('ResizableSplitPane', () => {
  it('renders stacked-friendly regions and resets ratio on double click', () => {
    localStorage.setItem(COLLECTION_SPLIT_STORAGE_KEY, '0.55')
    render(
      <ResizableSplitPane
        left={<div>left-pane</div>}
        right={<div>right-pane</div>}
      />,
    )
    expect(screen.getByText('left-pane')).toBeTruthy()
    expect(screen.getByText('right-pane')).toBeTruthy()
    const divider = screen.getByTestId('collection-split-divider')
    const left = screen.getByTestId('collection-split-left')
    expect(left.getAttribute('style')).toContain('55')
    fireEvent.doubleClick(divider)
    expect(left.getAttribute('style')).toContain(String((DEFAULT_COLLECTION_SPLIT_RATIO * 100).toFixed(0)).slice(0, 2))
  })

  it('adjusts ratio with keyboard arrows', () => {
    render(
      <ResizableSplitPane
        left={<div>left</div>}
        right={<div>right</div>}
      />,
    )
    const divider = screen.getByTestId('collection-split-divider')
    const left = screen.getByTestId('collection-split-left')
    const before = left.getAttribute('style') ?? ''
    fireEvent.keyDown(divider, { key: 'ArrowRight' })
    const after = left.getAttribute('style') ?? ''
    expect(after).not.toBe(before)
  })
})
