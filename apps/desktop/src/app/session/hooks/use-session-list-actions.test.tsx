import { act, render, renderHook } from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SessionInfo, SidebarSessionsRequest, SidebarSessionsResponse } from '@/hermes'
import { $sessionsLimit, resetSessionsLimit, SIDEBAR_SESSIONS_INITIAL_LIMIT } from '@/store/layout'
import { $showAllProfiles, setShowAllProfiles } from '@/store/profile'
import { $cronJobs, setCronJobs } from '@/store/cron'
import {
  beginGatewaySwitch,
  endGatewaySwitch,
  recoverActiveSourceAfterFailedGatewaySwitch,
  registerGatewaySwitchLifecycle
} from '@/store/gateway-switch'
import {
  $cronSessions,
  $messagingPlatformTotals,
  $messagingSessions,
  $sessionAllProfileTotals,
  $sessionProfileTotals,
  $messagingTruncated,
  $sessionProfilesTruncated,
  $sessionProfilesUsage,
  $sessions,
  $sessionsLoading,
  setCronSessions,
  setMessagingPlatformTotals,
  setMessagingSessions,
  setMessagingTruncated,
  setSessionProfilesTruncated,
  setSessionProfilesUsage,
  setSessions,
  setSessionsLoading
} from '@/store/session'

import { deferred } from '../../../test/deferred'

import { useSessionListActions } from './use-session-list-actions'

// Sidebar refresh hygiene: a content-identical refresh (turn complete,
// cross-window broadcast, reconnect) must not replace $sessions' array
// identity — that identity is the dependency for every sidebar memo — and
// must not flicker the loading flag over an already-populated list.

const row = (id: string, over: Partial<SessionInfo> = {}): SessionInfo =>
  ({
    ended_at: null,
    id,
    input_tokens: 0,
    is_active: false,
    last_active: 1000,
    message_count: 3,
    model: 'm',
    output_tokens: 0,
    preview: 'hey',
    profile: 'default',
    source: 'desktop',
    started_at: 900,
    title: `Chat ${id}`,
    ...over
  }) as SessionInfo

// Batched sidebar response builder. `refreshSessions` now makes ONE
// listSidebarSessions call that returns all three slices, replacing the three
// separate listAllProfileSessions calls (each of which reopened every profile
// DB) — #66377-adjacent perf work from the desktop audit canvas.
const sidebar = (
  recents: SidebarSessionsResponse["recents"],
  cron: SessionInfo[] = [],
  messaging: SessionInfo[] = []
): SidebarSessionsResponse => ({
  recents: { ...recents },
  cron: { sessions: cron },
  messaging: { sessions: messaging }
})

const listSidebarSessions = vi.fn()
const listAllProfileSessions = vi.fn()
const notify = vi.fn()
const getCronJobs = vi.fn()
const gatewayScope = vi.hoisted(() => ({ epoch: 0 }))

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

/** Create a promise whose completion order the stale-response tests control. */

vi.mock('@/hermes', async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>()
  return ({
  ...actual,
  getCronJobs: async (...args: unknown[]) => {
    const body = await getCronJobs(...args)
    return Array.isArray(body) ? {jobs: body, errors: []} : body
  },
  listAllProfileSessions: (...args: unknown[]) => listAllProfileSessions(...args),
  listSidebarSessions: (...args: unknown[]) => listSidebarSessions(...args)
})})

vi.mock('@/store/notifications', () => ({
  notify: (...args: unknown[]) => notify(...args),
  notifyError: vi.fn()

}))

vi.mock('@/store/gateway', async importOriginal => {
  const actual = await importOriginal<Record<string, unknown>>()
  return ({
  ...actual,
  gatewayActivationEpoch: () => gatewayScope.epoch
})})

// The refresh only reads the optimistic tombstone set; stub it so we don't pull
// the whole projects store (gateway / fs / git) into this hook's test.
const removed = vi.hoisted(() => ({ ids: new Set<string>() }))

vi.mock('@/store/session-removal', async importActual => ({
  ...(await importActual<Record<string, unknown>>()),
  $removedSessionIds: { get: () => removed.ids }
}))

beforeEach(() => {
  gatewayScope.epoch = 0
  getCronJobs.mockReset()
  getCronJobs.mockResolvedValue([])
  listSidebarSessions.mockReset()
  listAllProfileSessions.mockReset()
  notify.mockReset()
  setShowAllProfiles(false)
  $sessionsLimit.set(SIDEBAR_SESSIONS_INITIAL_LIMIT)
  removed.ids = new Set()
  setCronJobs([])
  setSessions([])
  setCronSessions([])
  setMessagingSessions([])
  setMessagingPlatformTotals({})
  setMessagingTruncated(false)
  setSessionProfilesTruncated({})
  setSessionProfilesUsage({})
  setSessionsLoading(false)
})

afterEach(() => {
  resetSessionsLimit()
  setCronJobs([])
  setSessions([])
  setCronSessions([])
  setMessagingSessions([])
  setMessagingPlatformTotals({})
  setMessagingTruncated(false)
  setSessionProfilesTruncated({})
  setSessionProfilesUsage({})
  setSessionsLoading(false)
  setShowAllProfiles(false)
})

// A concrete scope the backend doesn't recognize (profile deleted on disk, or
// a stray stored preference adopted at boot) used to come back as an empty
// recents slice with no error — the sidebar rendered permanently empty
// (observed 2026-08-31 with a ghost "diego" scope against 7,184 real
// sessions). The batched endpoint now echoes profile_matched; the hook must
// fall back to the all-profiles view and say so, once per ghost scope.
describe('ghost profile scope fallback', () => {
  const ghostResponse = (profile: string): SidebarSessionsResponse => ({
    recents: { sessions: [], total: 0, profile_totals: {}, profile, profile_matched: false },
    cron: { sessions: [] },
    messaging: { sessions: [], total: 0 }
  })

  it('flips to the all-profiles view and notifies once when the scope matches no profile', async () => {
    listSidebarSessions.mockResolvedValue(ghostResponse('diego'))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'diego' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($showAllProfiles.get()).toBe(true)
    expect(notify).toHaveBeenCalledTimes(1)
    expect($sessionsLoading.get()).toBe(false)

    // A repeat refresh against the same ghost scope re-asserts the fallback
    // without stacking another notification.
    setShowAllProfiles(false)

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($showAllProfiles.get()).toBe(true)
    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('leaves a matched-but-empty scope and an indicator-less backend alone', async () => {
    listSidebarSessions.mockResolvedValue({
      recents: { sessions: [], total: 0, profile_totals: { work: 0 }, profile: 'work', profile_matched: true },
      cron: { sessions: [] },
      messaging: { sessions: [], total: 0 }
    } satisfies SidebarSessionsResponse)

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($showAllProfiles.get()).toBe(false)
    expect(notify).not.toHaveBeenCalled()

    // Older backend / legacy per-slice fallback: no indicator field at all.
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [], total: 0 }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($showAllProfiles.get()).toBe(false)
    expect(notify).not.toHaveBeenCalled()
  })
})

describe('refreshSessions identity + loading hygiene', () => {
  it('keeps the previous $sessions array when the refresh is content-identical', async () => {
    const rows = [row('a'), row('b')]
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: rows, total: 2 }))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    const first = $sessions.get()
    expect(first.map(s => s.id)).toEqual(['a', 'b'])

    // Second refresh returns fresh (but equal) row objects, as the API does.
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a'), row('b')], total: 2 }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get()).toBe(first)
  })

  it('swaps the array when rows actually changed', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a')] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    const first = $sessions.get()

    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a', { last_active: 2000, title: 'Renamed' })] }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get()).not.toBe(first)
    expect($sessions.get()[0].title).toBe('Renamed')
  })

  it('does not flicker the loading flag over a populated list', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a')] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    const loadingStates: boolean[] = []
    const off = $sessionsLoading.subscribe(value => loadingStates.push(value))

    await act(async () => {
      await result.current.refreshSessions()
    })

    off()
    // Only the initial subscribe emission — no true/false churn per refresh.
    expect(loadingStates).toEqual([false])
  })

  it('drops rows the user just deleted, even when the backend page still lists them', async () => {
    // A delete RPC is in flight: the row is tombstoned optimistically but the
    // batched refresh still carries it (and a lineage-tip variant). Both must be
    // filtered so the optimistic removal never flashes back.
    removed.ids = new Set(['b', 'root-c'])
    listSidebarSessions.mockResolvedValue(
      sidebar({
        sessions: [row('a'), row('b'), row('c', { _lineage_root_id: 'root-c' } as Partial<SessionInfo>)]
      })
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get().map(s => s.id)).toEqual(['a'])
  })

  it('keeps idle recents when the sidebar returns an empty page plus profile errors', async () => {
    // Backend contract on disk I/O / lock: HTTP 200, recents=[], errors=[{profile}].
    // mergeSessionPage only keeps working/pinned/selected, so Yesterday/This-week
    // idle rows must be carried forward from the previous list — not clobbered.
    const idle = [row('yesterday'), row('week')]
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: idle }))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get().map(s => s.id)).toEqual(['yesterday', 'week'])

    setSessionProfilesTruncated({ default: true })
    setSessionProfilesUsage({ default: { cost_usd: 3, tokens: 30 } })
    setMessagingTruncated(true)

    listSidebarSessions.mockResolvedValue({
      ...sidebar({ sessions: [] }),
      errors: [{ error: 'disk I/O error', profile: 'default' }]
    })

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get().map(s => s.id)).toEqual(['yesterday', 'week'])
    expect($sessionProfilesTruncated.get()).toEqual({ default: true })
    expect($sessionProfilesUsage.get()).toEqual({ default: { cost_usd: 3, tokens: 30 } })
    expect($messagingTruncated.get()).toBe(true)
  })

  it('still accepts a genuine empty recents page when the backend reported no errors', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a')] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get()).toEqual([])
  })

  it('clears an empty scope without removing cached rows from another profile', async () => {
    setSessions([row('old'), row('other', { profile: 'work' })])
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get().map(session => session.id)).toEqual(['other'])
  })

  it('drops tombstoned rows from the messaging slice and per-platform paging too (#50928)', async () => {
    // The same delete race exists on every ingestion point: the batched
    // refresh's messaging slice and the per-platform "load more" pager must
    // both honor the tombstone, or a deleted platform thread resurrects.
    removed.ids = new Set(['tg-2'])
    listSidebarSessions.mockResolvedValue(
      sidebar({ sessions: [] }, [], [row('tg-1', { source: 'telegram' }), row('tg-2', { source: 'telegram' })])
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($messagingSessions.get().map(s => s.id)).toEqual(['tg-1'])

    // Per-platform pager: backend page still lists the doomed row.
    listAllProfileSessions.mockResolvedValue({
      sessions: [
        row('tg-1', { source: 'telegram' }),
        row('tg-2', { source: 'telegram' }),
        row('tg-3', { source: 'telegram' })
      ],
      total: 3
    })

    await act(async () => {
      await result.current.loadMoreMessagingForPlatform('telegram')
    })

    expect($messagingSessions.get().map(s => s.id)).toEqual(['tg-1', 'tg-3'])
  })

  it('still shows loading for the initial (empty-list) fetch', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [row('a')] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    const loadingStates: boolean[] = []
    const off = $sessionsLoading.subscribe(value => loadingStates.push(value))

    await act(async () => {
      await result.current.refreshSessions()
    })

    off()
    expect(loadingStates).toEqual([false, true, false])
  })

  it('does not let a superseded owner publish or release a newer switch loading barrier', async () => {
    const pending = deferred<SidebarSessionsResponse>()
    let ownsRefresh = true

    listSidebarSessions.mockReturnValue(pending.promise)

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))
    const refresh = result.current.refreshSessions(() => ownsRefresh)

    expect($sessionsLoading.get()).toBe(true)

    ownsRefresh = false
    setSessions([row('winner')])
    setCronSessions([row('winner-cron', { source: 'cron' })])
    setMessagingSessions([row('winner-message', { source: 'signal' })])
    setMessagingTruncated(true)
    setSessionProfilesTruncated({ winner: true })
    setSessionProfilesUsage({ winner: { cost_usd: 2, tokens: 20 } })
    setSessionsLoading(true)

    await act(async () => {
      pending.resolve({
        recents: {
          profiles_truncated: { stale: true },
          profiles_usage: { stale: { cost_usd: 1, tokens: 10 } },
          sessions: [row('stale')]
        },
        cron: { sessions: [row('stale-cron', { source: 'cron' })] },
        messaging: { sessions: [row('stale-message', { source: 'telegram' })] }
      })
      await refresh
    })

    expect($sessions.get().map(session => session.id)).toEqual(['winner'])
    expect($cronSessions.get().map(session => session.id)).toEqual(['winner-cron'])
    expect($messagingSessions.get().map(session => session.id)).toEqual(['winner-message'])
    expect($messagingTruncated.get()).toBe(true)
    expect($sessionProfilesTruncated.get()).toEqual({ winner: true })
    expect($sessionProfilesUsage.get()).toEqual({ winner: { cost_usd: 2, tokens: 20 } })
    expect($sessionsLoading.get()).toBe(true)
    expect(getCronJobs).not.toHaveBeenCalled()
  })

  it('keeps failed-switch recovery from publishing through a newer switch', async () => {
    const pending = deferred<SidebarSessionsResponse>()

    listSidebarSessions.mockReturnValue(pending.promise)

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    const off = registerGatewaySwitchLifecycle({
      beforeConnectionSwitch: () => undefined,
      refreshSessions: result.current.refreshSessions
    })

    let newer: number | undefined

    try {
      const failed = beginGatewaySwitch()

      recoverActiveSourceAfterFailedGatewaySwitch(failed)
      endGatewaySwitch(failed)
      await vi.waitFor(() => expect(listSidebarSessions).toHaveBeenCalledTimes(1))

      // A newer switch owns the freshly wiped lists and loading barrier while
      // the failed switch's real sidebar publisher is still in flight.
      newer = beginGatewaySwitch()

      await act(async () => {
        pending.resolve({
          recents: {
            profiles_truncated: { stale: true },
            profiles_usage: { stale: { cost_usd: 1, tokens: 10 } },
            sessions: [row('stale')]
          },
          cron: { sessions: [row('stale-cron', { source: 'cron' })] },
          messaging: { sessions: [row('stale-message', { source: 'telegram' })] }
        })
        await pending.promise
      })

      expect($sessions.get()).toEqual([])
      expect($cronSessions.get()).toEqual([])
      expect($messagingSessions.get()).toEqual([])
      expect($messagingTruncated.get()).toBe(false)
      expect($sessionProfilesTruncated.get()).toEqual({})
      expect($sessionProfilesUsage.get()).toEqual({})
      expect($sessionsLoading.get()).toBe(true)
      expect($cronJobs.get()).toEqual([])
      expect(getCronJobs).not.toHaveBeenCalled()
    } finally {
      endGatewaySwitch(newer)
      off()
    }
  })

  it('clears initial loading after a failed source activation advances the gateway epoch', async () => {
    const pending = deferred<SidebarSessionsResponse>()
    listSidebarSessions.mockReturnValue(pending.promise)
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    let refresh!: Promise<void>

    act(() => {
      refresh = result.current.refreshSessions()
    })

    expect($sessionsLoading.get()).toBe(true)

    // A source dial owns a new activation epoch even when it fails and leaves
    // the previous source active. Its in-flight session response is stale, but
    // it still owns the initial loading state and must release that state.
    gatewayScope.epoch += 1

    await act(async () => {
      pending.resolve(sidebar({ sessions: [row('stale')] }))
      await refresh
    })

    expect($sessions.get()).toEqual([])
    expect($sessionsLoading.get()).toBe(false)
  })
})

describe('refreshSessions batches slices into one request', () => {
  it('hydrates a cold 501-row total in bounded 0/500 pages, then skips stable rehydration', async () => {
    const rows = Array.from({ length: SIDEBAR_SESSIONS_INITIAL_LIMIT + 1 }, (_, index) =>
      row(`session-${index + 1}`, { last_active: SIDEBAR_SESSIONS_INITIAL_LIMIT - index })
    )

    listSidebarSessions.mockResolvedValue(
      sidebar({
        sessions: rows.slice(0, SIDEBAR_SESSIONS_INITIAL_LIMIT),
        total: rows.length,
        profile_totals: { default: rows.length }
      })
    )
    listAllProfileSessions.mockImplementation(
      (
        limit: number,
        _minMessages: number,
        _archived: string,
        _order: string,
        profile: string,
        filter: { offset?: number } = {}
      ) => {
        const offset = filter.offset ?? 0

        return Promise.resolve({
          limit,
          offset,
          profile_totals: { [profile]: rows.length },
          sessions: rows.slice(offset, offset + limit),
          total: rows.length
        })
      }
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(
      listAllProfileSessions.mock.calls.map(call => ({ limit: call[0], offset: call[5]?.offset ?? 0 }))
    ).toEqual([
      { limit: SIDEBAR_SESSIONS_INITIAL_LIMIT, offset: 0 },
      { limit: SIDEBAR_SESSIONS_INITIAL_LIMIT, offset: SIDEBAR_SESSIONS_INITIAL_LIMIT }
    ])
    expect(new Set($sessions.get().map(session => session.id)).size).toBe(rows.length)
    expect($sessions.get()).toHaveLength(rows.length)

    listSidebarSessions.mockClear()
    listAllProfileSessions.mockClear()

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listSidebarSessions).toHaveBeenCalledTimes(1)
    expect(listSidebarSessions).toHaveBeenCalledWith(
      expect.objectContaining({ recentsLimit: SIDEBAR_SESSIONS_INITIAL_LIMIT })
    )
    expect(listAllProfileSessions).not.toHaveBeenCalled()
  })

  it('rehydrates a stable profile again after a soft gateway switch clears the session cache', async () => {
    const rows = Array.from({ length: SIDEBAR_SESSIONS_INITIAL_LIMIT + 1 }, (_, index) =>
      row(`session-${index + 1}`, { last_active: SIDEBAR_SESSIONS_INITIAL_LIMIT - index })
    )

    listSidebarSessions.mockResolvedValue(
      sidebar({
        sessions: rows.slice(0, SIDEBAR_SESSIONS_INITIAL_LIMIT),
        total: rows.length,
        profile_totals: { default: rows.length }
      })
    )
    listAllProfileSessions.mockImplementation(
      (
        limit: number,
        _minMessages: number,
        _archived: string,
        _order: string,
        profile: string,
        filter: { offset?: number } = {}
      ) => {
        const offset = filter.offset ?? 0

        return Promise.resolve({
          limit,
          offset,
          profile_totals: { [profile]: rows.length },
          sessions: rows.slice(offset, offset + limit),
          total: rows.length
        })
      }
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessions.get()).toHaveLength(rows.length)

    // Connection/mode apply wipes gateway-bound stores without remounting this
    // hook. The new backend may expose the same profile name and total.
    setSessions([])
    listAllProfileSessions.mockClear()

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listAllProfileSessions.mock.calls.map(call => call[5]?.offset)).toEqual([
      0,
      SIDEBAR_SESSIONS_INITIAL_LIMIT
    ])
    expect($sessions.get()).toHaveLength(rows.length)
    expect($sessions.get().some(session => session.id === rows.at(-1)!.id)).toBe(true)
  })

  it('rehydrates a concrete profile when its explicit total changes', async () => {
    let rows = [row('session-1'), row('session-2')]

    listSidebarSessions.mockImplementation((request: SidebarSessionsRequest) =>
      Promise.resolve(
        sidebar({
          sessions: rows.slice(0, request.recentsLimit),
          total: rows.length,
          profile_totals: { default: rows.length }
        })
      )
    )
    listAllProfileSessions.mockImplementation(
      (
        limit: number,
        _minMessages: number,
        _archived: string,
        _order: string,
        profile: string,
        filter: { offset?: number } = {}
      ) => {
        const offset = filter.offset ?? 0

        return Promise.resolve({
          limit,
          offset,
          profile_totals: { [profile]: rows.length },
          sessions: rows.slice(offset, offset + limit),
          total: rows.length
        })
      }
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    rows = [...rows, row('session-3')]

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listAllProfileSessions).toHaveBeenCalledTimes(2)
    expect(listAllProfileSessions.mock.calls.map(call => call[5]?.offset)).toEqual([0, 0])
    expect($sessions.get().map(session => session.id)).toEqual(['session-1', 'session-2', 'session-3'])
  })

  it('does not hydrate or reconcile a fractional initial explicit total', async () => {
    const cached = [row('session-newest'), row('session-oldest', { last_active: 1 })]

    setSessions(cached)
    listSidebarSessions.mockResolvedValue(
      sidebar({ sessions: [cached[0]], total: 1.5, profile_totals: { default: 1.5 } })
    )
    listAllProfileSessions.mockResolvedValue({
      limit: SIDEBAR_SESSIONS_INITIAL_LIMIT,
      offset: 0,
      profile_totals: { default: 1 },
      sessions: [cached[0]],
      total: 1
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
      await result.current.refreshSessions()
    })

    expect(listAllProfileSessions).not.toHaveBeenCalled()
    expect($sessions.get().some(session => session.id === 'session-oldest')).toBe(true)
    expect($sessions.get()).toHaveLength(cached.length)
  })

  it('retries hydration when a concrete page overshoots its advertised total', async () => {
    const cached = [row('session-newest'), row('session-oldest', { last_active: 1 })]
    const unexpected = row('session-unexpected', { last_active: 500 })

    setSessions(cached)
    listSidebarSessions.mockResolvedValue(
      sidebar({ sessions: [cached[0]], total: 1, profile_totals: { default: 1 } })
    )
    listAllProfileSessions.mockResolvedValue({
      limit: SIDEBAR_SESSIONS_INITIAL_LIMIT,
      offset: 0,
      profile_totals: { default: 1 },
      sessions: [cached[0], unexpected],
      total: 1
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
      await result.current.refreshSessions()
    })

    // Overshoot is non-authoritative and is not memoized, so a later refresh
    // retries hydration without removing the cached tail.
    expect(listAllProfileSessions).toHaveBeenCalledTimes(2)
    expect($sessions.get().some(session => session.id === 'session-oldest')).toBe(true)
    expect($sessions.get()).toHaveLength(cached.length)
  })

  it('preserves the oldest cached row when a concrete page total drifts from the batched target', async () => {
    const cached = [row('session-newest'), row('session-oldest', { last_active: 1 })]
    const batchedTotal = 1

    setSessions(cached)
    listSidebarSessions.mockResolvedValue(
      sidebar({
        sessions: [cached[0]],
        total: batchedTotal,
        profile_totals: { default: batchedTotal }
      })
    )
    listAllProfileSessions.mockResolvedValue({
      limit: SIDEBAR_SESSIONS_INITIAL_LIMIT,
      offset: 0,
      profile_totals: { default: batchedTotal + 1 },
      sessions: [cached[0]],
      total: batchedTotal + 1
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
      await result.current.refreshSessions()
    })

    // Total drift makes both concrete responses non-authoritative, so the
    // cached catalog remains additive and hydration is retried later.
    expect(listAllProfileSessions).toHaveBeenCalledTimes(2)
    expect($sessions.get().some(session => session.id === 'session-oldest')).toBe(true)
    expect($sessions.get()).toHaveLength(cached.length)
  })

  it.each(['throws', 'returns no progress'] as const)(
    'keeps the oldest cached row when a later hydration page %s',
    async failure => {
      const rows = Array.from({ length: SIDEBAR_SESSIONS_INITIAL_LIMIT + 1 }, (_, index) =>
        row(`session-${index + 1}`, { last_active: SIDEBAR_SESSIONS_INITIAL_LIMIT - index })
      )

      const oldestId = rows.at(-1)!.id

      setSessions(rows)
      listSidebarSessions.mockResolvedValue(
        sidebar({
          sessions: rows.slice(0, SIDEBAR_SESSIONS_INITIAL_LIMIT),
          total: rows.length,
          profile_totals: { default: rows.length }
        })
      )
      listAllProfileSessions.mockImplementation(
        (
          limit: number,
          _minMessages: number,
          _archived: string,
          _order: string,
          _profile: string,
          filter: { offset?: number } = {}
        ) => {
          const offset = filter.offset ?? 0

          if (offset === SIDEBAR_SESSIONS_INITIAL_LIMIT) {
            if (failure === 'throws') {
              return Promise.reject(new Error('page failed'))
            }

            return Promise.resolve({ limit, offset, sessions: [], total: rows.length })
          }

          return Promise.resolve({
            limit,
            offset,
            sessions: rows.slice(offset, offset + limit),
            total: rows.length
          })
        }
      )

      const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

      await act(async () => {
        await result.current.refreshSessions()
      })

      expect(listAllProfileSessions.mock.calls.map(call => call[5]?.offset)).toEqual([
        0,
        SIDEBAR_SESSIONS_INITIAL_LIMIT
      ])
      expect($sessions.get().some(session => session.id === oldestId)).toBe(true)
      expect($sessions.get()).toHaveLength(rows.length)
    }
  )

  it.each(['reports errors', 'returns an empty first page'] as const)(
    'preserves cached rows and does not reconcile when hydration %s',
    async failure => {
      const cached = [row('session-1'), row('session-oldest', { last_active: 1 })]

      setSessions(cached)
      listSidebarSessions.mockResolvedValue(
        sidebar({ sessions: [], total: cached.length, profile_totals: { default: cached.length } })
      )
      listAllProfileSessions.mockImplementation((limit: number, ...args: unknown[]) => {
        const filter = (args[4] as { offset?: number } | undefined) ?? {}
        const page = { limit, offset: filter.offset ?? 0, sessions: [], total: cached.length }

        return Promise.resolve(
          failure === 'reports errors' ? { ...page, errors: [{ error: 'remote failed', profile: 'default' }] } : page
        )
      })

      const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

      await act(async () => {
        await result.current.refreshSessions()
      })

      expect(listAllProfileSessions).toHaveBeenCalledTimes(1)
      expect($sessions.get()).toBe(cached)
      expect($sessions.get().map(session => session.id)).toContain('session-oldest')
    }
  )

  it('preserves cached rows and skips reconciliation for result errors with an empty first page', async () => {
    const cached = [
      row('remote-newest', { profile: 'remote' }),
      row('remote-oldest', { last_active: 1, profile: 'remote' })
    ]

    setSessions(cached)
    listSidebarSessions.mockResolvedValue({
      ...sidebar({ sessions: [], total: 0, profile_totals: { remote: 0 } }),
      errors: [{ error: 'remote failed', profile: 'remote' }]
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'remote' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listAllProfileSessions).not.toHaveBeenCalled()
    expect($sessions.get()).toBe(cached)
  })

  it('does not invent an authoritative concrete total when profile_totals omits that profile', async () => {
    const cached = [
      row('remote-newest', { profile: 'remote' }),
      row('remote-oldest', { last_active: 1, profile: 'remote' })
    ]

    setSessions(cached)
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [], total: 0, profile_totals: {} }))
    listAllProfileSessions.mockResolvedValue({
      limit: SIDEBAR_SESSIONS_INITIAL_LIMIT,
      offset: 0,
      sessions: [],
      total: 0
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'remote' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listAllProfileSessions).not.toHaveBeenCalled()
    expect($sessions.get()).toBe(cached)
  })

  it('makes a single sidebar call and distributes recents / cron / messaging', async () => {
    const recents = [row('a'), row('b')]
    const cron = [row('c1', { source: 'cron', title: 'nightly' })]
    const messaging = [row('m1', { source: 'telegram', title: 'tg chat' })]

    listSidebarSessions.mockResolvedValue(sidebar({ sessions: recents, total: 2 }, cron, messaging))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    // One batched call, not three separate listAllProfileSessions reads.
    expect(listSidebarSessions).toHaveBeenCalledTimes(1)
    expect(listAllProfileSessions).not.toHaveBeenCalled()

    // Each slice landed in its own store.
    expect($sessions.get().map(s => s.id)).toEqual(['a', 'b'])
    expect($cronSessions.get().map(s => s.id)).toEqual(['c1'])
    expect($messagingSessions.get().map(s => s.id)).toEqual(['m1'])
  })

  it('forwards the active profile scope + section limits to the batched call', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(listSidebarSessions).toHaveBeenCalledWith(
      expect.objectContaining({
        recentsProfile: 'work',
        recentsExclude: expect.arrayContaining(['cron']),
        messagingExclude: expect.arrayContaining(['cron'])
      })
    )
  })

  it('does not start a refresh callback captured before a profile switch', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    const staleRefresh = result.current.refreshSessions

    rerender({ profileScope: 'personal' })

    await act(async () => {
      await staleRefresh()
    })

    expect(listSidebarSessions).not.toHaveBeenCalled()
  })

  it('keeps the committed profile active when a later render is discarded', async () => {
    const never = new Promise<never>(() => undefined)
    let committedRefresh: (() => Promise<void>) | undefined

    /** Expose only callbacks from committed renders; suspended renders are discarded. */
    function Harness({ profileScope, suspend }: { profileScope: string; suspend: boolean }) {
      const actions = useSessionListActions({ profileScope })

      if (suspend) {
        throw never
      }

      committedRefresh = actions.refreshSessions

      return null
    }

    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))

    const view = render(
      <Suspense fallback={null}>
        <Harness profileScope="work" suspend={false} />
      </Suspense>
    )

    const workRefresh = committedRefresh!

    view.rerender(
      <Suspense fallback={null}>
        <Harness profileScope="personal" suspend />
      </Suspense>
    )

    await act(async () => {
      await workRefresh()
    })

    expect(listSidebarSessions).toHaveBeenCalledWith(expect.objectContaining({ recentsProfile: 'work' }))
  })

  it('ignores an in-flight sidebar response after the active profile changes', async () => {
    const work = deferred<SidebarSessionsResponse>()
    const personal = deferred<SidebarSessionsResponse>()

    listSidebarSessions.mockImplementation(({ recentsProfile }) =>
      recentsProfile === 'work' ? work.promise : personal.promise
    )

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    const workRefresh = result.current.refreshSessions()

    rerender({ profileScope: 'personal' })
    const personalRefresh = result.current.refreshSessions()

    await act(async () => {
      personal.resolve(
        sidebar(
          { sessions: [row('personal-session', { profile: 'personal' })] },
          [row('personal-cron', { profile: 'personal', source: 'cron' })],
          [row('personal-signal', { profile: 'personal', source: 'signal' })]
        )
      )
      await personalRefresh

      work.resolve(
        sidebar(
          { sessions: [row('work-session', { profile: 'work' })] },
          [row('work-cron', { profile: 'work', source: 'cron' })],
          [row('work-telegram', { profile: 'work', source: 'telegram' })]
        )
      )
      await workRefresh
    })

    expect($sessions.get().map(session => session.id)).toEqual(['personal-session'])
    expect($cronSessions.get().map(session => session.id)).toEqual(['personal-cron'])
    expect($messagingSessions.get().map(session => session.id)).toEqual(['personal-signal'])
  })

  it('ignores an in-flight response after the source changes with the same profile', async () => {
    const work = deferred<SidebarSessionsResponse>()
    const personal = deferred<SidebarSessionsResponse>()

    listSidebarSessions.mockReturnValueOnce(work.promise).mockReturnValueOnce(personal.promise)
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))
    const workRefresh = result.current.refreshSessions()

    gatewayScope.epoch += 1
    const personalRefresh = result.current.refreshSessions()

    await act(async () => {
      personal.resolve(
        sidebar({ sessions: [row('personal-session')] }, [], [row('personal-chat', { source: 'telegram' })])
      )
      await personalRefresh

      work.resolve(sidebar({ sessions: [row('work-session')] }, [], [row('work-chat', { source: 'signal' })]))
      await workRefresh
    })

    expect($sessions.get().map(session => session.id)).toEqual(['personal-session'])
    expect($messagingSessions.get().map(session => session.id)).toEqual(['personal-chat'])
  })

  it('scopes the cron-jobs fetch to the active profile', async () => {
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }))

    const scoped = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await scoped.result.current.refreshCronJobs()
    })

    expect(getCronJobs).toHaveBeenLastCalledWith('work')
  })

  it('requests cron jobs for the unified scope', async () => {
    const unified = renderHook(() => useSessionListActions({ profileScope: '__all__' }))

    await act(async () => {
      await unified.result.current.refreshCronJobs()
    })

    expect(getCronJobs).toHaveBeenLastCalledWith('all')
  })

  it('ignores an out-of-order cron-jobs response from the previous profile', async () => {
    const work = deferred<Array<{ enabled: boolean; id: string }>>()
    const personal = deferred<Array<{ enabled: boolean; id: string }>>()

    getCronJobs.mockImplementation((profile: string) => (profile === 'work' ? work.promise : personal.promise))

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    const workRefresh = result.current.refreshCronJobs()

    rerender({ profileScope: 'personal' })
    const personalRefresh = result.current.refreshCronJobs()

    await act(async () => {
      personal.resolve([{ enabled: true, id: 'personal-job' }])
      await personalRefresh

      work.resolve([{ enabled: true, id: 'work-job' }])
      await workRefresh
    })

    expect(getCronJobs.mock.calls.map(call => call[0])).toEqual(['work', 'personal'])
    expect($cronJobs.get().map(job => job.id)).toEqual(['personal-job'])
  })
})

describe('messaging profile scope', () => {
  it('refreshes messaging sessions only for the active profile', async () => {
    listAllProfileSessions.mockResolvedValue({
      sessions: [row('m1', { profile: 'work', source: 'signal' })],
      total: 1
    })
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await result.current.refreshMessagingSessions()
    })

    expect(listAllProfileSessions).toHaveBeenCalledWith(
      expect.any(Number),
      1,
      'exclude',
      'recent',
      'work',
      expect.objectContaining({ excludeSources: expect.any(Array) })
    )
    expect($messagingSessions.get().map(s => s.id)).toEqual(['m1'])
  })

  it('keeps the explicit all-profiles view unified', async () => {
    listAllProfileSessions.mockResolvedValue({ sessions: [], total: 0 })
    const { result } = renderHook(() => useSessionListActions({ profileScope: '__all__' }))

    await act(async () => {
      await result.current.refreshMessagingSessions()
    })

    expect(listAllProfileSessions.mock.calls[0][4]).toBe('all')
  })

  it('keeps per-platform pagination on the active profile', async () => {
    setMessagingSessions([row('m1', { profile: 'work', source: 'signal' })])
    listAllProfileSessions.mockResolvedValue({
      sessions: [row('m1', { profile: 'work', source: 'signal' }), row('m2', { profile: 'work', source: 'signal' })],
      total: 2
    })
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await result.current.loadMoreMessagingForPlatform('signal')
    })

    expect(listAllProfileSessions.mock.calls[0][4]).toBe('work')
    expect($messagingSessions.get().map(s => s.id)).toEqual(['m1', 'm2'])
    expect($messagingPlatformTotals.get()).toEqual({ 'work:signal': 2 })
  })

  it('keeps rows from every profile when paginating the unified scope', async () => {
    setMessagingSessions([row('work-signal', { profile: 'work', source: 'signal' })])
    listAllProfileSessions.mockResolvedValue({
      sessions: [
        row('work-signal', { profile: 'work', source: 'signal' }),
        row('personal-signal', { profile: 'personal', source: 'signal' })
      ],
      total: 2
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: '__all__' }))

    await act(async () => {
      await result.current.loadMoreMessagingForPlatform('signal')
    })

    expect(listAllProfileSessions.mock.calls[0][4]).toBe('all')
    expect($messagingSessions.get().map(session => session.id)).toEqual(['work-signal', 'personal-signal'])
    expect($messagingPlatformTotals.get()).toEqual({ 'all:signal': 2 })
  })

  it('keeps loaded platform rows when pagination fails', async () => {
    const loaded = [row('work-signal', { profile: 'work', source: 'signal' })]
    setMessagingSessions(loaded)
    setMessagingPlatformTotals({ 'work:signal': 12 })
    listAllProfileSessions.mockRejectedValue(new Error('request failed'))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))

    await act(async () => {
      await expect(result.current.loadMoreMessagingForPlatform('signal')).resolves.toBeUndefined()
    })

    expect($messagingSessions.get()).toEqual(loaded)
    expect($messagingPlatformTotals.get()).toEqual({ 'work:signal': 12 })
  })

  it('keeps resolved platform totals separate across profile switches', async () => {
    listAllProfileSessions.mockResolvedValue({
      sessions: [row('work-signal', { profile: 'work', source: 'signal' })],
      total: 42
    })

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    await act(async () => {
      await result.current.loadMoreMessagingForPlatform('signal')
    })

    expect($messagingPlatformTotals.get()).toEqual({ 'work:signal': 42 })

    rerender({ profileScope: 'personal' })

    expect($messagingPlatformTotals.get()['personal:signal']).toBeUndefined()
    expect($messagingPlatformTotals.get()['work:signal']).toBe(42)

    listAllProfileSessions.mockResolvedValue({
      sessions: [row('personal-signal', { profile: 'personal', source: 'signal' })],
      total: 3
    })

    await act(async () => {
      await result.current.loadMoreMessagingForPlatform('signal')
    })

    expect($messagingPlatformTotals.get()).toEqual({ 'personal:signal': 3, 'work:signal': 42 })

    rerender({ profileScope: 'work' })

    expect($messagingPlatformTotals.get()['work:signal']).toBe(42)
  })

  it('ignores an older overlapping load-more response for the same profile and platform', async () => {
    const older = deferred<{ sessions: SessionInfo[]; total: number }>()
    const newer = deferred<{ sessions: SessionInfo[]; total: number }>()

    setMessagingSessions([row('m1', { profile: 'work', source: 'signal' })])
    listAllProfileSessions.mockImplementationOnce(() => older.promise).mockImplementationOnce(() => newer.promise)

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'work' }))
    const olderLoad = result.current.loadMoreMessagingForPlatform('signal')

    setMessagingSessions([
      row('m1', { profile: 'work', source: 'signal' }),
      row('m2', { profile: 'work', source: 'signal' })
    ])
    const newerLoad = result.current.loadMoreMessagingForPlatform('signal')

    await act(async () => {
      newer.resolve({
        sessions: [
          row('m1', { profile: 'work', source: 'signal' }),
          row('m2', { profile: 'work', source: 'signal' }),
          row('m3', { profile: 'work', source: 'signal' })
        ],
        total: 3
      })
      await newerLoad

      older.resolve({
        sessions: [row('m1', { profile: 'work', source: 'signal' }), row('m2', { profile: 'work', source: 'signal' })],
        total: 2
      })
      await olderLoad
    })

    expect($messagingSessions.get().map(session => session.id)).toEqual(['m1', 'm2', 'm3'])
    expect($messagingPlatformTotals.get()).toEqual({ 'work:signal': 3 })
  })

  it('ignores an in-flight response after the active profile changes', async () => {
    const work = deferred<{ sessions: SessionInfo[]; total: number }>()
    const personal = deferred<{ sessions: SessionInfo[]; total: number }>()

    listAllProfileSessions.mockImplementation((_limit, _min, _archived, _order, profile) =>
      profile === 'work' ? work.promise : personal.promise
    )

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    const workRefresh = result.current.refreshMessagingSessions()
    rerender({ profileScope: 'personal' })
    const personalRefresh = result.current.refreshMessagingSessions()

    await act(async () => {
      personal.resolve({
        sessions: [row('personal-message', { profile: 'personal', source: 'telegram' })],
        total: 1
      })
      await personalRefresh
      work.resolve({ sessions: [row('work-message', { profile: 'work', source: 'signal' })], total: 1 })
      await workRefresh
    })

    expect(listAllProfileSessions.mock.calls.map(call => call[4])).toEqual(['work', 'personal'])
    expect($messagingSessions.get().map(session => session.id)).toEqual(['personal-message'])
  })

  it('does not let a callback captured before a profile switch disturb current totals', async () => {
    listAllProfileSessions.mockResolvedValue({ sessions: [], total: 0 })
    setMessagingPlatformTotals({ 'work:signal': 12 })

    const { rerender, result } = renderHook(({ profileScope }) => useSessionListActions({ profileScope }), {
      initialProps: { profileScope: 'work' }
    })

    const staleRefresh = result.current.refreshMessagingSessions

    rerender({ profileScope: 'personal' })

    await act(async () => {
      await staleRefresh()
    })

    expect(listAllProfileSessions).not.toHaveBeenCalled()
    expect($messagingPlatformTotals.get()).toEqual({ 'work:signal': 12 })
  })
})

describe('loadMoreSessionsForProfile bounded paging', () => {
  it('requests one bounded next page and additively preserves the rank-51 row', async () => {
    const previous = Array.from({ length: 51 }, (_, index) => row(`session-${index + 1}`))
    const incoming = [row('session-52'), row('session-53')]
    const otherProfile = row('work-1', { profile: 'work' })

    setSessions([...previous, otherProfile])
    listAllProfileSessions.mockResolvedValue({
      limit: SIDEBAR_SESSIONS_INITIAL_LIMIT,
      offset: previous.length,
      profile_totals: { default: previous.length + incoming.length },
      sessions: incoming,
      total: previous.length + incoming.length
    })

    const { result } = renderHook(() => useSessionListActions({ profileScope: '__all__' }))

    await act(async () => {
      await result.current.loadMoreSessionsForProfile('default')
    })

    expect(listAllProfileSessions).toHaveBeenCalledTimes(1)
    expect(listAllProfileSessions).toHaveBeenCalledWith(
      SIDEBAR_SESSIONS_INITIAL_LIMIT,
      1,
      'exclude',
      'recent',
      'default',
      expect.objectContaining({ offset: previous.length })
    )

    const ids = $sessions.get().map(session => session.id)

    expect(ids).toContain('session-51')
    expect(ids).toContain('session-53')
    expect(ids).toContain(otherProfile.id)
    expect(new Set(ids).size).toBe(previous.length + incoming.length + 1)
  })
})

// The cross-profile aggregate DROPS a profile whose store it cannot read (a
// locked or corrupt state.db, or one with no sessions table) and returns the
// survivors as if complete. Measured on this box 2026-09-07: every single
// sidebar call carries [{profile: 'matcher', error: 'no such table: sessions'}]
// and nothing surfaced it, so a partial list rendered as a whole one.
describe('partial aggregate failure is surfaced', () => {
  const withErrors = (errors: Array<{ profile: string; error: string }>): SidebarSessionsResponse => ({
    recents: {
      sessions: [],
      total: 0,
      profile_totals: { default: 0 },
      profile: 'all',
      profile_matched: true
    },
    cron: { sessions: [] },
    messaging: { sessions: [], total: 0 },
    errors
  })

  it('notifies once, naming the unreadable profile', async () => {
    listSidebarSessions.mockResolvedValue(
      withErrors([{ profile: 'matcher', error: 'no such table: sessions' }])
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'all' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(notify).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(notify.mock.calls[0])).toContain('matcher')

    // A persistent failure must not re-notify on every poll.
    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(notify).toHaveBeenCalledTimes(1)
  })

  it('stays silent when every profile answered', async () => {
    listSidebarSessions.mockResolvedValue(withErrors([]))

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'all' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(notify).not.toHaveBeenCalled()
  })

  it('re-notifies when a DIFFERENT profile starts failing', async () => {
    listSidebarSessions.mockResolvedValue(
      withErrors([{ profile: 'matcher', error: 'no such table: sessions' }])
    )

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'all' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    listSidebarSessions.mockResolvedValue(withErrors([{ profile: 'scout', error: 'database is locked' }]))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect(notify).toHaveBeenCalledTimes(2)
    expect(JSON.stringify(notify.mock.calls[1])).toContain('scout')
  })

  it('stores every profile total, not just the scoped one', async () => {
    // Feeds the scoped-but-empty sidebar state. Under a concrete scope
    // profile_totals carries only its own key, so this must come from the
    // separate all_profile_totals field.
    listSidebarSessions.mockResolvedValue({
      recents: {
        sessions: [],
        total: 0,
        profile_totals: { main: 0 },
        all_profile_totals: { default: 8309, main: 0 },
        profile: 'main',
        profile_matched: true
      },
      cron: { sessions: [] },
      messaging: { sessions: [], total: 0 }
    } satisfies SidebarSessionsResponse)

    const { result } = renderHook(() => useSessionListActions({ profileScope: 'main' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($sessionAllProfileTotals.get()).toEqual({ default: 8309, main: 0 })
    // The scoped map stays scoped -- it drives catalog hydration.
    expect($sessionProfileTotals.get()).toEqual({ main: 0 })
  })
})
