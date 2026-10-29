import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  clampCollectionSplitRatio,
  DEFAULT_COLLECTION_SPLIT_RATIO,
  readCollectionSplitRatio,
  writeCollectionSplitRatio,
} from '../../lib/collectionSplit'

type ResizableSplitPaneProps = {
  left: ReactNode
  right: ReactNode
  className?: string
}

export function ResizableSplitPane({ left, right, className }: ResizableSplitPaneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [leftRatio, setLeftRatio] = useState(() => readCollectionSplitRatio())
  const draggingRef = useRef(false)

  const applyRatio = useCallback((next: number, persist = true) => {
    const width = containerRef.current?.getBoundingClientRect().width ?? 0
    const clamped = clampCollectionSplitRatio(next, width)
    setLeftRatio(clamped)
    if (persist) {
      writeCollectionSplitRatio(clamped)
    }
  }, [])

  useEffect(() => {
    const onResize = () => {
      if (draggingRef.current) {
        return
      }
      applyRatio(leftRatio, false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [applyRatio, leftRatio])

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (window.matchMedia('(max-width: 900px)').matches) {
      return
    }
    event.preventDefault()
    draggingRef.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    document.body.classList.add('collection-split-dragging')
  }

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !containerRef.current) {
      return
    }
    const rect = containerRef.current.getBoundingClientRect()
    const next = (event.clientX - rect.left) / rect.width
    applyRatio(next, true)
  }

  const onPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) {
      return
    }
    draggingRef.current = false
    document.body.classList.remove('collection-split-dragging')
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      /* already released */
    }
  }

  const onDoubleClick = () => {
    applyRatio(DEFAULT_COLLECTION_SPLIT_RATIO, true)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
      return
    }
    event.preventDefault()
    const delta = event.key === 'ArrowLeft' ? -0.02 : 0.02
    applyRatio(leftRatio + delta, true)
  }

  const leftPercent = `${(leftRatio * 100).toFixed(4)}%`

  return (
    <div ref={containerRef} className={`collection-split${className ? ` ${className}` : ''}`} data-testid="collection-split">
      <div
        className="collection-split-left"
        style={{ flexBasis: leftPercent, maxWidth: leftPercent }}
        data-testid="collection-split-left"
      >
        {left}
      </div>
      <div
        className="collection-split-divider"
        data-testid="collection-split-divider"
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={45}
        aria-valuemax={78}
        aria-valuenow={Math.round(leftRatio * 100)}
        aria-label="调整左右栏宽度"
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
      >
        <span className="collection-split-grip" aria-hidden="true" />
      </div>
      <div className="collection-split-right" data-testid="collection-split-right">{right}</div>
    </div>
  )
}
