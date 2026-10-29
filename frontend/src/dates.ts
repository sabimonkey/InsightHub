export function formatIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function calendarDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

export function addDays(date: Date, days: number): Date {
  const next = calendarDay(date)
  next.setDate(next.getDate() + days)
  return next
}

export function startOfIsoWeek(date: Date): Date {
  const next = calendarDay(date)
  const day = next.getDay()
  const offset = day === 0 ? 6 : day - 1
  next.setDate(next.getDate() - offset)
  return next
}

export type DatePreset = 'today' | 'yesterday' | 'last7' | 'thisWeek' | 'lastWeek' | 'thisMonth' | 'lastMonth' | 'custom'

export function resolvePreset(preset: DatePreset, today = new Date()): { start: string; end: string } {
  const current = calendarDay(today)
  if (preset === 'today' || preset === 'custom') {
    const day = formatIsoDate(current)
    return { start: day, end: day }
  }
  if (preset === 'yesterday') {
    const day = formatIsoDate(addDays(current, -1))
    return { start: day, end: day }
  }
  if (preset === 'last7') {
    return { start: formatIsoDate(addDays(current, -6)), end: formatIsoDate(current) }
  }
  if (preset === 'thisWeek') {
    const start = startOfIsoWeek(current)
    return { start: formatIsoDate(start), end: formatIsoDate(current) }
  }
  if (preset === 'lastWeek') {
    const start = addDays(startOfIsoWeek(current), -7)
    return { start: formatIsoDate(start), end: formatIsoDate(addDays(start, 6)) }
  }
  if (preset === 'thisMonth') {
    const start = new Date(current.getFullYear(), current.getMonth(), 1)
    return { start: formatIsoDate(start), end: formatIsoDate(current) }
  }
  const start = new Date(current.getFullYear(), current.getMonth() - 1, 1)
  const end = new Date(current.getFullYear(), current.getMonth(), 0)
  return { start: formatIsoDate(start), end: formatIsoDate(end) }
}
