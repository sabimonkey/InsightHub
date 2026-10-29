export type CoverTheme =
  | 'knowledge'
  | 'business'
  | 'project_discovery'
  | 'other'
  | 'url'
  | 'text'
  | 'file'
  | 'github'
  | 'x'
  | 'default'

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0
  }
  return hash
}

export function resolveCoverTheme(
  sourceId: string,
  categories: string[] | undefined,
  sourceType: string | null | undefined,
): { theme: CoverTheme; variant: number } {
  const slug = (categories?.[0] || '').toLowerCase()
  let theme: CoverTheme = 'default'
  if (slug === 'knowledge' || slug === 'business' || slug === 'project_discovery' || slug === 'other') {
    theme = slug as CoverTheme
  } else {
    const type = (sourceType || '').toUpperCase()
    if (type === 'URL') theme = 'url'
    else if (type === 'TEXT') theme = 'text'
    else if (type === 'FILE') theme = 'file'
    else if (type === 'GITHUB') theme = 'github'
    else if (type === 'X') theme = 'x'
  }
  const variant = hashString(sourceId) % 4
  return { theme, variant }
}
