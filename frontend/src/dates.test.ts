import { describe, expect, it } from 'vitest'
import { resolvePreset, startOfIsoWeek } from './dates'

describe('brief date presets', () => {
  const wednesday = new Date(2026, 8, 23)

  it('uses Monday through Sunday for ISO weeks', () => {
    expect(startOfIsoWeek(wednesday).getDate()).toBe(21)
    expect(startOfIsoWeek(new Date(2026, 8, 27)).getDate()).toBe(21)
    const week = resolvePreset('thisWeek', wednesday)
    expect(week).toEqual({ start: '2026-09-21', end: '2026-09-23' })
    expect(resolvePreset('lastWeek', wednesday)).toEqual({ start: '2026-09-14', end: '2026-09-20' })
  })

  it('resolves month ranges to fixed dates', () => {
    expect(resolvePreset('thisMonth', wednesday)).toEqual({ start: '2026-09-01', end: '2026-09-23' })
    expect(resolvePreset('thisMonth', new Date(2026, 9, 20))).toEqual({ start: '2026-10-01', end: '2026-10-20' })
    expect(resolvePreset('lastMonth', wednesday)).toEqual({ start: '2026-08-01', end: '2026-08-31' })
    expect(resolvePreset('today', wednesday)).toEqual({ start: '2026-09-23', end: '2026-09-23' })
    expect(resolvePreset('yesterday', wednesday)).toEqual({ start: '2026-09-22', end: '2026-09-22' })
    expect(resolvePreset('last7', wednesday)).toEqual({ start: '2026-09-17', end: '2026-09-23' })
  })
})
