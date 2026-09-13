import { ALL_PROFILES, normalizeProfileKey } from '@/store/profile'

/** Showable sessions that live OUTSIDE `scope`.
 *
 *  Reads the ALL-profiles map, never a scoped one: under a concrete scope the scoped maps
 *  carry only that profile's own key, so the comparison number is absent from them by
 *  construction. A backend that does not send `all_profile_totals` yields 0 here, which
 *  leaves every caller inert rather than wrong.
 */
export function elsewhereSessionTotal(allProfileTotals: Record<string, number>, scope: string): number {
  if (scope === ALL_PROFILES) {
    return 0
  }

  const target = normalizeProfileKey(scope)

  return Object.entries(allProfileTotals).reduce(
    (sum, [key, count]) => (normalizeProfileKey(key) === target ? sum : sum + (count || 0)),
    0
  )
}

/** THE THIRD EMPTY STATE.
 *
 *  A scope that MATCHES, a request that SUCCEEDS, and a result that is legitimately ZERO.
 *  The ghost-scope fallback fires only on `profile_matched === false`, and the failed-request
 *  states fire only on a rejection; between them sits a real, recognized, populated profile
 *  that simply holds none of the session class this slice shows (recents excludes
 *  cron/subagent/tool/messaging, and a profile can be 100% those). Measured 2026-09-07:
 *  ~/.hermes/profiles/main held 1,132 such sessions, so scoping there rendered a confident
 *  empty sidebar over 8,309 showable chats in the default profile.
 *
 *  Deliberately narrow. It must not fire when the user is in the unified view, when rows are
 *  merely filtered out of an otherwise populated profile, or when this profile genuinely has
 *  chats that simply have not loaded — only when THIS profile's own count is a real zero and
 *  some other profile's is not.
 */
export function isScopedEmptyWithRowsElsewhere(args: {
  allProfileTotals: Record<string, number>
  scope: string
  scopedTotal: number | undefined
  visibleCount: number
}): boolean {
  const { allProfileTotals, scope, scopedTotal, visibleCount } = args

  if (scope === ALL_PROFILES || visibleCount > 0) {
    return false
  }

  const ownTotal = allProfileTotals[normalizeProfileKey(scope)] ?? scopedTotal

  return ownTotal === 0 && elsewhereSessionTotal(allProfileTotals, scope) > 0
}
