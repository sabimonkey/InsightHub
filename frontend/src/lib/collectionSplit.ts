export const COLLECTION_SPLIT_STORAGE_KEY = 'insighthub.collection.splitRatio'

export const DEFAULT_COLLECTION_SPLIT_RATIO = 2 / 3

export const MIN_COLLECTION_SPLIT_RATIO = 0.45

export const MAX_COLLECTION_SPLIT_RATIO = 0.78

export function normalizeCollectionSplitRatio(value: unknown): number {
  const numeric = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''))
  if (!Number.isFinite(numeric)) {
    return DEFAULT_COLLECTION_SPLIT_RATIO
  }
  if (numeric < MIN_COLLECTION_SPLIT_RATIO || numeric > MAX_COLLECTION_SPLIT_RATIO) {
    return DEFAULT_COLLECTION_SPLIT_RATIO
  }
  return numeric
}

export function readCollectionSplitRatio(storage: Pick<Storage, 'getItem'> = localStorage): number {
  try {
    return normalizeCollectionSplitRatio(storage.getItem(COLLECTION_SPLIT_STORAGE_KEY))
  } catch {
    return DEFAULT_COLLECTION_SPLIT_RATIO
  }
}

export function writeCollectionSplitRatio(ratio: number, storage: Pick<Storage, 'setItem'> = localStorage): number {
  const normalized = normalizeCollectionSplitRatio(ratio)
  try {
    storage.setItem(COLLECTION_SPLIT_STORAGE_KEY, String(normalized))
  } catch {
    /* ignore quota / private mode */
  }
  return normalized
}

export function clampCollectionSplitRatio(ratio: number, containerWidth: number, minRightPx = 300, minLeftPx = 520): number {
  if (!Number.isFinite(containerWidth) || containerWidth <= 0) {
    return normalizeCollectionSplitRatio(ratio)
  }
  const minRatio = Math.max(MIN_COLLECTION_SPLIT_RATIO, minLeftPx / containerWidth)
  const maxRatio = Math.min(MAX_COLLECTION_SPLIT_RATIO, (containerWidth - minRightPx) / containerWidth)
  const safeMax = Math.max(minRatio, maxRatio)
  return Math.min(safeMax, Math.max(minRatio, ratio))
}
