import { describe, expect, it } from 'vitest'

import { ALL_PROFILES } from '@/store/profile'

import { elsewhereSessionTotal, isScopedEmptyWithRowsElsewhere } from './scoped-empty'

describe('elsewhereSessionTotal', () => {
  it('sums every profile except the scoped one', () => {
    expect(elsewhereSessionTotal({ default: 8309, main: 0, work: 12 }, 'main')).toBe(8321)
  })

  it('is zero in the unified view — there is no "elsewhere"', () => {
    expect(elsewhereSessionTotal({ default: 8309, main: 0 }, ALL_PROFILES)).toBe(0)
  })

  it('is zero when the backend omits the map (older gateway)', () => {
    expect(elsewhereSessionTotal({}, 'main')).toBe(0)
  })
})

describe('isScopedEmptyWithRowsElsewhere', () => {
  const base = { allProfileTotals: { default: 8309, main: 0 }, scope: 'main', scopedTotal: 0, visibleCount: 0 }

  it('THE CASE IT EXISTS FOR: matched, populated, and showing nothing', () => {
    expect(isScopedEmptyWithRowsElsewhere(base)).toBe(true)
  })

  it('stays inert when rows are actually on screen', () => {
    expect(isScopedEmptyWithRowsElsewhere({ ...base, visibleCount: 3 })).toBe(false)
  })

  it('stays inert in the unified view', () => {
    expect(isScopedEmptyWithRowsElsewhere({ ...base, scope: ALL_PROFILES })).toBe(false)
  })

  it('stays inert when no other profile has chats either', () => {
    expect(isScopedEmptyWithRowsElsewhere({ ...base, allProfileTotals: { default: 0, main: 0 } })).toBe(false)
  })

  it('stays inert when THIS profile does have chats that simply have not loaded', () => {
    expect(isScopedEmptyWithRowsElsewhere({ ...base, allProfileTotals: { default: 8309, main: 4 } })).toBe(false)
  })

  it('stays inert against an older backend that omits all_profile_totals', () => {
    expect(isScopedEmptyWithRowsElsewhere({ ...base, allProfileTotals: {} })).toBe(false)
  })

  it('falls back to the scoped total when the cross-profile map lacks this profile', () => {
    expect(
      isScopedEmptyWithRowsElsewhere({ ...base, allProfileTotals: { default: 8309 }, scopedTotal: 0 })
    ).toBe(true)
  })
})
