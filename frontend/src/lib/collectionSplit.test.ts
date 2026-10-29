import { describe, expect, it } from 'vitest'
import {
  COLLECTION_SPLIT_STORAGE_KEY,
  DEFAULT_COLLECTION_SPLIT_RATIO,
  clampCollectionSplitRatio,
  normalizeCollectionSplitRatio,
  readCollectionSplitRatio,
  writeCollectionSplitRatio,
} from './collectionSplit'

describe('collectionSplit', () => {
  it('uses default ratio when storage is missing or invalid', () => {
    const storage = { getItem: () => null, setItem: () => undefined }
    expect(readCollectionSplitRatio(storage)).toBe(DEFAULT_COLLECTION_SPLIT_RATIO)
    expect(normalizeCollectionSplitRatio('not-a-number')).toBe(DEFAULT_COLLECTION_SPLIT_RATIO)
    expect(normalizeCollectionSplitRatio(Infinity)).toBe(DEFAULT_COLLECTION_SPLIT_RATIO)
    expect(normalizeCollectionSplitRatio(0.2)).toBe(DEFAULT_COLLECTION_SPLIT_RATIO)
    expect(normalizeCollectionSplitRatio(0.9)).toBe(DEFAULT_COLLECTION_SPLIT_RATIO)
  })

  it('restores valid stored ratio', () => {
    const bag = new Map<string, string>()
    const storage = {
      getItem: (key: string) => bag.get(key) ?? null,
      setItem: (key: string, value: string) => {
        bag.set(key, value)
      },
    }
    writeCollectionSplitRatio(0.62, storage)
    expect(bag.get(COLLECTION_SPLIT_STORAGE_KEY)).toBe('0.62')
    expect(readCollectionSplitRatio(storage)).toBe(0.62)
  })

  it('clamps drag ratio with pixel minimums', () => {
    const wide = clampCollectionSplitRatio(0.9, 1400)
    expect(wide).toBeLessThanOrEqual(0.78)
    expect(wide).toBeGreaterThan(0.45)
    const narrow = clampCollectionSplitRatio(0.1, 900)
    expect(narrow).toBeGreaterThanOrEqual(0.45)
  })
})
