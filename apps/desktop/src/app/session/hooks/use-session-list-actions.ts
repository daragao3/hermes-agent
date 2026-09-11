import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'

import { listAllProfileSessions, listSidebarSessions, type SessionInfo } from '@/hermes'
import { translateNow } from '@/i18n'
import { notify } from '@/store/notifications'
import { sameCronSignature } from '@/lib/session-signatures'
import {
  isMessagingSource,
  LOCAL_SESSION_SOURCE_IDS,
  MESSAGING_SESSION_SOURCE_IDS,
  normalizeSessionSource
} from '@/lib/session-source'
import { gatewayActivationEpoch } from '@/store/gateway'
import {
  $pinnedSessionIds,
  $sessionsLimit,
  $sidebarFiltersActive,
  bumpSessionsLimit,
  raiseSessionsLimit,
  SIDEBAR_FILTERED_PAGE_SIZE,
  SIDEBAR_SESSIONS_INITIAL_LIMIT,
  SIDEBAR_SESSIONS_PAGE_SIZE
} from '@/store/layout'
import { messagingTotalsKey, normalizeProfileKey, sidebarProfileForScope, setShowAllProfiles } from '@/store/profile'
import {
  $messagingSessions,
  $selectedStoredSessionId,
  $sessions,
  carryForwardFailedProfileSessions,
  CRON_SECTION_LIMIT,
  keepFailedProfileMeta,
  mergeSessionPage,
  MESSAGING_SECTION_LIMIT,
  setCronSessions,
  setMessagingPlatformTotals,
  setMessagingSessions,
  setMessagingTruncated,
  setSessionAllProfileTotals,
  setSessionProfileTotals,
  setSessionProfilesTruncated,
  setSessionProfilesUsage,
  setSessions,
  setSessionsLoading
} from '@/store/session'
import { $removedSessionIds } from '@/store/session-removal'
import { $sessionTiles, $workingSessionIds, getRecentlySettledSessionIds } from '@/store/session-states'

import { refreshCronJobs as refreshCronJobsStore } from '../../cron/cron-actions'

// The recents list is local-only: cron rows have their own section, kanban
// dispatcher workers are read on the board, and each messaging platform
// (telegram, discord, …) is fetched separately into its own self-managed
// sidebar section (refreshMessagingSessions). Excluding them here keeps
// "Load more" paging through interactive local chats instead of
// interleaving gateway threads that bury them.
const SIDEBAR_EXCLUDED_SOURCES = ['cron', 'kanban', 'subagent', 'tool', ...MESSAGING_SESSION_SOURCE_IDS]
// The messaging slice is the inverse: drop cron + every local source so only
// external-platform conversations remain, then split per platform in the UI.
const MESSAGING_EXCLUDED_SOURCES = ['cron', ...LOCAL_SESSION_SOURCE_IDS]

// Drop rows the user just deleted/archived: ANY list fetch (full refresh,
// "Load more" paging, a per-platform messaging page, the cron slice) can race
// an in-flight delete RPC, and the backend page still carries the doomed row
// until the DELETE commits — so it flashed back into the sidebar (#50928).
// Honoring the optimistic tombstone at every ingestion point keeps the removal
// stable; the tombstone self-clears once projects.tree confirms the delete,
// and a failed delete untombstones immediately, so nothing is filtered on the
// non-destructive paths.
function dropTombstoned(sessions: SessionInfo[]): SessionInfo[] {
  const tombstones = $removedSessionIds.get()

  return tombstones.size
    ? sessions.filter(s => !tombstones.has(s.id) && !(s._lineage_root_id && tombstones.has(s._lineage_root_id)))
    : sessions
}

// Rows a session refresh must preserve even if the aggregator omits them:
// in-flight first turns (message_count 0), pinned rows aged off the page, the
// actively-viewed chat (its "working" flag clears a beat before the aggregator
// sees the persisted row), and sessions whose turn just settled (same race, but
// for a chat the user has already navigated away from). Pass `scope` to only
// keep the active row when it belongs to the profile being paged.
function sessionsToKeep(scope?: string): Set<string> {
  const keep = new Set<string>([
    ...$workingSessionIds.get(),
    ...$pinnedSessionIds.get(),
    ...getRecentlySettledSessionIds()
  ])

  // Open tiles are user-visible state exactly like the selected row: a branch
  // child is a DRAFT until its first real turn, so the aggregator can't return
  // it — without this the next background refresh silently dropped the
  // optimistic `draft: branch #N` row while its tab was open, and the sidebar
  // showed no trace of the branch until first send.
  for (const tile of $sessionTiles.get()) {
    keep.add(tile.storedSessionId)
  }

  const active = $selectedStoredSessionId.get()

  if (active) {
    const session = scope ? $sessions.get().find(s => s.id === active) : null

    if (!scope || !session || normalizeProfileKey(session.profile) === scope) {
      keep.add(active)
    }
  }

  return keep
}

interface UseSessionListActionsArgs {
  profileScope: string
}

/** Owns the sidebar's session-list fetching + paging: recents, cron runs/jobs,
 *  and the per-platform messaging slices. Returns the callbacks the controller
 *  wires into the sidebar and refresh effects. */
export function useSessionListActions({ profileScope }: UseSessionListActionsArgs) {
  const profileScopeRef = useRef(profileScope)
  const loadMoreMessagingRequestRef = useRef<Record<string, number>>({})
  const refreshMessagingSessionsRequestRef = useRef(0)
  const refreshSessionsRequestRef = useRef(0)
  const hydratedProfileTotalsRef = useRef<Map<string, number>>(new Map())
  const hydrationEpochRef = useRef<number | undefined>(undefined)
  const ghostScopeNotifiedRef = useRef<null | string>(null)
  const sessionsPartialNotifiedRef = useRef<null | string>(null)

  useLayoutEffect(() => {
    profileScopeRef.current = profileScope
  }, [profileScope])

  /** Refresh the active profile's messaging-platform sidebar slice. */
  const refreshMessagingSessions = useCallback(async () => {
    const sessionProfile = sidebarProfileForScope(profileScope)
    const activationEpoch = gatewayActivationEpoch()

    // A callback captured before a profile switch may still be queued by an
    // event subscription. Do not let it start a request against the old scope.
    if (sidebarProfileForScope(profileScopeRef.current) !== sessionProfile) {
      return
    }

    const requestId = refreshMessagingSessionsRequestRef.current + 1
    refreshMessagingSessionsRequestRef.current = requestId

    try {
      const result = await listAllProfileSessions(MESSAGING_SECTION_LIMIT, 1, 'exclude', 'recent', sessionProfile, {
        excludeSources: MESSAGING_EXCLUDED_SOURCES
      })

      if (
        refreshMessagingSessionsRequestRef.current !== requestId ||
        sidebarProfileForScope(profileScopeRef.current) !== sessionProfile ||
        gatewayActivationEpoch() !== activationEpoch
      ) {
        return
      }

      // Drop any non-messaging source the broad exclude didn't catch (custom
      // sources) — those stay in local recents, not a platform section.
      const rows = dropTombstoned(result.sessions.filter(s => isMessagingSource(s.source)))

      setMessagingSessions(prev => (sameCronSignature(prev, rows) ? prev : rows))
      // Hit the cap → at least one platform may have more on disk than loaded,
      // so platform sections offer their own per-platform "load more".
      setMessagingTruncated(result.sessions.length >= MESSAGING_SECTION_LIMIT)
    } catch {
      // Non-fatal: the messaging sections just stay empty/stale.
    }
  }, [profileScope])

  /** Page one messaging platform without replacing another platform's rows. */
  const loadMoreMessagingForPlatform = useCallback(
    async (platform: string) => {
      const sessionProfile = sidebarProfileForScope(profileScope)
      const activationEpoch = gatewayActivationEpoch()

      if (sidebarProfileForScope(profileScopeRef.current) !== sessionProfile) {
        return
      }

      const requestKey = messagingTotalsKey(sessionProfile, platform)
      const requestId = (loadMoreMessagingRequestRef.current[requestKey] ?? 0) + 1
      loadMoreMessagingRequestRef.current[requestKey] = requestId

      const inProfile = (s: SessionInfo) =>
        sessionProfile === 'all' || normalizeProfileKey(s.profile) === sessionProfile

      const inPlatform = (s: SessionInfo) => normalizeSessionSource(s.source) === platform && inProfile(s)
      const loaded = $messagingSessions.get().filter(inPlatform).length

      let result

      try {
        result = await listAllProfileSessions(
          loaded + SIDEBAR_SESSIONS_PAGE_SIZE,
          1,
          'exclude',
          'recent',
          sessionProfile,
          { source: platform }
        )
      } catch {
        // Non-fatal: leave the platform's loaded rows and total unchanged.
        return
      }

      if (
        loadMoreMessagingRequestRef.current[requestKey] !== requestId ||
        sidebarProfileForScope(profileScopeRef.current) !== sessionProfile ||
        gatewayActivationEpoch() !== activationEpoch
      ) {
        return
      }

      const incoming = dropTombstoned(result.sessions.filter(inPlatform))

      setMessagingSessions(prev => [
        ...prev.filter(s => !inPlatform(s)),
        ...mergeSessionPage(
          prev.filter(inPlatform),
          carryForwardFailedProfileSessions(prev.filter(inPlatform), incoming, result.errors),
          sessionsToKeep()
        )
      ])

      const total = result.total ?? incoming.length

      setMessagingPlatformTotals(prev => ({ ...prev, [requestKey]: Math.max(total, incoming.length) }))
    },
    [profileScope]
  )

  /** Refresh cron jobs only while the profile that requested them remains active. */
  const refreshCronJobs = useCallback(async () => {
    const sessionProfile = sidebarProfileForScope(profileScope)

    if (sidebarProfileForScope(profileScopeRef.current) !== sessionProfile) {
      return
    }

    try {
      await refreshCronJobsStore(sessionProfile)
    } catch {
      // Non-fatal: the cron section just keeps its last-known jobs.
    }
  }, [profileScope])

  /** Refresh every sidebar session slice without committing an obsolete profile response. */
  const refreshSessions = useCallback(
    async (shouldPublish: () => boolean = () => true) => {
      const sessionProfile = sidebarProfileForScope(profileScope)
      const activationEpoch = gatewayActivationEpoch()

      if (!shouldPublish() || sidebarProfileForScope(profileScopeRef.current) !== sessionProfile) {
        return
      }

      const requestId = refreshSessionsRequestRef.current + 1
      refreshSessionsRequestRef.current = requestId
      const canPublish = () => shouldPublish() && refreshSessionsRequestRef.current === requestId
        && sidebarProfileForScope(profileScopeRef.current) === sessionProfile
        && gatewayActivationEpoch() === activationEpoch
      if ($sessions.get().length === 0 || hydrationEpochRef.current !== activationEpoch) {
        hydratedProfileTotalsRef.current.clear()
        hydrationEpochRef.current = activationEpoch
      }
      // The loading flag exists to drive the initial skeletons (they only render
      // while the list is empty). Turn-complete / reconnect refreshes over a
      // populated list used to flip it true→false anyway, churning every
      // $sessionsLoading subscriber twice per turn for no visible change.
      const showLoading = $sessions.get().length === 0

      if (showLoading && shouldPublish()) {
        setSessionsLoading(true)
      }

      try {
        const limit = Math.min(Math.max(1, $sessionsLimit.get()), SIDEBAR_SESSIONS_INITIAL_LIMIT)

        // Require at least one message so abandoned/empty "Untitled" drafts (one
        // was created per TUI/desktop launch before the lazy-create fix) don't
        // clutter the sidebar.
        // Unified cross-profile list (served read-only off each profile's
        // state.db; no per-profile backend is spawned). Single-profile users get
        // the same rows tagged profile="default".
        // Scope every sidebar slice to the active profile (not always 'all') so a profile
        // with few recent sessions isn't windowed out of the cross-profile
        // recency page and never inherits another profile's cron or messaging
        // sections. ALL_PROFILES remains the explicit unified view.
        // Batched: one request opens each profile DB once and returns all three
        // source-scoped slices, instead of three separate listAllProfileSessions
        // calls that each reopened + re-counted every profile DB per refresh.
        const result = await listSidebarSessions({
          recentsProfile: sessionProfile,
          recentsLimit: limit,
          recentsExclude: SIDEBAR_EXCLUDED_SOURCES,
          cronLimit: CRON_SECTION_LIMIT,
          messagingLimit: MESSAGING_SECTION_LIMIT,
          messagingExclude: MESSAGING_EXCLUDED_SOURCES
        })

        if (
          shouldPublish() &&
          refreshSessionsRequestRef.current === requestId &&
          sidebarProfileForScope(profileScopeRef.current) === sessionProfile &&
          gatewayActivationEpoch() === activationEpoch
        ) {
        // A concrete scope the backend doesn't recognize (profile deleted on
        // disk, or a stray stored preference adopted at boot) matches zero
        // profile DBs and comes back as an empty recents slice with no error —
        // left alone, the sidebar renders permanently empty. Fall back to the
        // all-profiles view (the scope change re-runs this refresh) and tell
        // the user once. `=== false` keeps older backends and the legacy
        // per-slice fallback (no indicator) on today's behavior.
        if (sessionProfile !== 'all' && result.recents.profile_matched === false) {
          if (ghostScopeNotifiedRef.current !== sessionProfile) {
            ghostScopeNotifiedRef.current = sessionProfile
            notify({
              kind: 'info',
              title: translateNow('desktop.profileScopeMissingTitle'),
              message: translateNow('desktop.profileScopeMissingMessage', sessionProfile)
            })
          }

          setShowAllProfiles(true)

          return
        }

          const recents = result.recents

          // Drop rows the user just deleted/archived: a refresh can race an
          // in-flight mutation and the backend page still carries the doomed row.
          // Honoring the optimistic tombstone keeps the removal from flashing back
          // (the tombstone self-clears once projects.tree confirms the delete).
          // Signature-gate the swap (same pattern as cron/messaging): a refresh
          // that returns content-identical rows must keep the previous array
          // identity, or every sidebar memo keyed on $sessions recomputes and the
          // whole list re-renders once per turn/broadcast for nothing.
          setSessions(prev => {
            const incoming = dropTombstoned(
              carryForwardFailedProfileSessions(prev, recents.sessions ?? [], recents.errors ?? result.errors)
            )

            const keep = sessionsToKeep()
            const hasCountMetadata = recents.total !== undefined || recents.profile_totals !== undefined
            const scopeTotal = sessionProfile === 'all' ? recents.total : recents.profile_totals?.[sessionProfile]
            const emptyScope = incoming.length === 0 && !(recents.errors ?? result.errors)?.length
              && (!hasCountMetadata || scopeTotal === 0)
            // A successful empty scope is authoritative. Keep additive paging
            // for populated/partial responses and preserve other profiles.
            // Count-bearing backends must explicitly confirm this scope is
            // empty; a missing profile count or incomplete page is not proof.
            for (const row of dropTombstoned(prev)) {
              if (!emptyScope || (sessionProfile !== 'all' && normalizeProfileKey(row.profile) !== sessionProfile)) {
                keep.add(row.id)
              }
            }
            const next = mergeSessionPage(dropTombstoned(prev), incoming, keep)

            return sameCronSignature(prev, next) ? prev : next
          })
        // Every profile's count, not just the scoped one. Feeds the
        // scoped-but-genuinely-empty sidebar state; deliberately NOT merged
        // into $sessionProfileTotals, which is iterated below to pick catalogs
        // to hydrate and must stay scoped.
        setSessionAllProfileTotals(prev => {
          const next = recents.all_profile_totals ?? {}
          const prevKeys = Object.keys(prev)

          return prevKeys.length === Object.keys(next).length && prevKeys.every(key => prev[key] === next[key])
            ? prev
            : next
        })
        setSessionProfileTotals(prev => {
          const next = recents.profile_totals ?? {}
          const prevKeys = Object.keys(prev)

          return prevKeys.length === Object.keys(next).length && prevKeys.every(key => prev[key] === next[key])
            ? prev
            : next
        })

          // "Is there another page?" instead of an exact total: the backend
          // reports which profiles filled their window, which costs nothing on
          // top of the rows it already read (the old exact totals ran a COUNT(*)
          // per profile DB on every refresh). Reference-stable when unchanged so
          // the sidebar's group memos don't recompute per refresh.
          const recentsErrors = recents.errors ?? result.errors
          setSessionProfilesTruncated(prev => {
            const next = keepFailedProfileMeta(prev, recents.profiles_truncated ?? {}, recentsErrors)
            const prevKeys = Object.keys(prev)

            return prevKeys.length === Object.keys(next).length && prevKeys.every(key => prev[key] === next[key])
              ? prev
              : next
          })
          // Same identity gate: these totals only move when a session bills, and
          // a fresh object every refresh would repaint every profile header.
          setSessionProfilesUsage(prev => {
            const next = keepFailedProfileMeta(prev, recents.profiles_usage ?? {}, recentsErrors)
            const prevKeys = Object.keys(prev)

            return prevKeys.length === Object.keys(next).length &&
              prevKeys.every(
                key => prev[key]?.tokens === next[key]?.tokens && prev[key]?.cost_usd === next[key]?.cost_usd
              )
              ? prev
              : next
          })

          // Cron section: latest N cron sessions (kept so a pinned cron run still
          // resolves via sessionByAnyId), signature-gated like above.
          setCronSessions(prev => {
            const incoming = carryForwardFailedProfileSessions(
              prev,
              result.cron.sessions ?? [],
              result.cron.errors ?? result.errors
            )

            return sameCronSignature(prev, incoming) ? prev : incoming
          })

          // Messaging sections: drop any non-messaging source the broad exclude
          // didn't catch (custom sources stay in local recents), then split per
          // platform in the UI.
          const messagingErrors = result.messaging.errors ?? result.errors
          setMessagingSessions(prev => {
            const messagingRows = dropTombstoned(
              carryForwardFailedProfileSessions(
                prev,
                (result.messaging.sessions ?? []).filter(s => isMessagingSource(s.source)),
                messagingErrors
              )
            )

            return sameCronSignature(prev, messagingRows) ? prev : messagingRows
          })
          // Hit the cap → at least one platform may have more on disk than loaded.
          setMessagingTruncated(prev =>
            messagingErrors?.length ? prev : result.messaging.sessions.length >= MESSAGING_SECTION_LIMIT
          )
        // Totals tell us which concrete profile catalogs are stale. A stable
        // total needs only the bounded batched refresh above; a changed total
        // is hydrated sequentially in fixed-size concrete-profile pages.
        const authoritativeTotals = new Map<string, number>()

        for (const [profile, total] of Object.entries(recents.profile_totals ?? {})) {
          if (typeof total === 'number' && Number.isFinite(total) && total >= 0 && Number.isInteger(total)) {
            authoritativeTotals.set(normalizeProfileKey(profile), total)
          }
        }

        const failedProfiles = new Set(
          (recents.errors ?? result.errors ?? []).map(error => (error.profile === 'all' ? 'all' : normalizeProfileKey(error.profile)))
        )

        // A profile whose store cannot be read (locked, corrupt, no sessions
        // table) is dropped from the aggregate and the rest are returned as if
        // complete -- a partial list rendered as a whole one. Say it once per
        // distinct failure set, the same shape as the ghost-scope notice above.
        if ((recents.errors ?? result.errors)?.length) {
          const signature = [...failedProfiles].sort().join(',')

          if (sessionsPartialNotifiedRef.current !== signature) {
            sessionsPartialNotifiedRef.current = signature
            notify({
              kind: 'warning',
              title: translateNow('desktop.sessionsPartialTitle'),
              message: translateNow('desktop.sessionsPartialMessage', [...failedProfiles].join(', '))
            })
          }
        } else {
          sessionsPartialNotifiedRef.current = null
        }

        for (const [profile, total] of authoritativeTotals) {
          if (!canPublish()) {
            break
          }

          if (
            failedProfiles.has('all') ||
            failedProfiles.has(profile) ||
            hydratedProfileTotalsRef.current.get(profile) === total
          ) {
            continue
          }

          const hydratedRows: SessionInfo[] = []
          const seenIds = new Set<string>()
          let complete = true
          let offset = 0

          do {
            if (!canPublish()) {
              complete = false

              break
            }

            let page

            try {
              page = await listAllProfileSessions(
                SIDEBAR_SESSIONS_INITIAL_LIMIT,
                1,
                'exclude',
                'recent',
                profile,
                { excludeSources: SIDEBAR_EXCLUDED_SOURCES, offset }
              )
            } catch {
              complete = false

              break
            }

            if (!canPublish() || page.errors?.length) {
              complete = false

              break
            }

            const concreteTotal = page.profile_totals?.[profile] ?? page.total

            // Every concrete page must describe the same complete catalog as
            // the batched response that triggered this hydration. A missing,
            // synthetic, malformed, or drifted total makes the page additive
            // only: never reconcile cached rows or memoize this hydration.
            if (
              typeof concreteTotal !== 'number' ||
              !Number.isFinite(concreteTotal) ||
              concreteTotal < 0 ||
              !Number.isInteger(concreteTotal) ||
              concreteTotal !== total
            ) {
              complete = false

              break
            }

            const rows = page.sessions

            // An empty first page authoritatively confirms a zero-total
            // profile. Anywhere else it is a stalled pagination cursor.
            if (rows.length === 0) {
              if (total !== 0 || offset !== 0) {
                complete = false
              }

              break
            }

            // A concrete-profile request must never leak another owner's row;
            // reconciling that response could delete one profile and insert a
            // different one's sessions in its place.
            if (rows.some(session => normalizeProfileKey(session.profile) !== profile)) {
              complete = false

              break
            }

            for (const session of rows) {
              if (seenIds.has(session.id)) {
                complete = false

                break
              }

              seenIds.add(session.id)
              hydratedRows.push(session)
            }

            if (!complete || rows.length < SIDEBAR_SESSIONS_INITIAL_LIMIT || seenIds.size >= total) {
              break
            }

            offset += SIDEBAR_SESSIONS_INITIAL_LIMIT
          } while (offset <= total)

          // A cursor/page failure, total drift that left us short, or a stale
          // request can update nothing authoritatively. Keep the additive first
          // page and every cached row, and retry on a later refresh.
          if (!complete || seenIds.size !== total || !canPublish()) {
            continue
          }

          const keep = sessionsToKeep(profile)

          setSessions(prev => {
            const inProfile = (session: SessionInfo) => normalizeProfileKey(session.profile) === profile
            const previousForProfile = prev.filter(inProfile)
            const reconciledProfile = mergeSessionPage(dropTombstoned(previousForProfile), dropTombstoned(hydratedRows), keep)
            const next = [...prev.filter(session => !inProfile(session)), ...reconciledProfile]

            return sameCronSignature(prev, next) ? prev : next
          })
          hydratedProfileTotalsRef.current.set(profile, total)
        }
        }
      } catch {
        // A failed page never replaces a previously published cache.
      } finally {
        // Request identity preserves the zero-argument refresh contract across a
        // failed activation epoch; an explicit owner predicate is stronger and
        // must never release a newer switch's loading barrier.
        if (showLoading && shouldPublish() && refreshSessionsRequestRef.current === requestId) {
          setSessionsLoading(false)
        }
      }

      // Cron *jobs* are a distinct API (getCronJobs), not a session slice.
      if (shouldPublish() && sidebarProfileForScope(profileScopeRef.current) === sessionProfile) {
        void refreshCronJobs()
      }
    },
    [profileScope, refreshCronJobs]
  )

  const loadMoreSessions = useCallback(async () => {
    bumpSessionsLimit()
    await refreshSessions()
  }, [refreshSessions])

  // ALL-profiles view pages one profile at a time: fetch that profile's next
  // page and merge it in place, leaving every other profile's rows untouched.
  const loadMoreSessionsForProfile = useCallback(async (profile: string) => {
    const key = normalizeProfileKey(profile)
    const ownerScope = sidebarProfileForScope(profileScopeRef.current)
    const epoch = gatewayActivationEpoch()
    const requestId = refreshSessionsRequestRef.current
    if (ownerScope !== 'all' && ownerScope !== key) return
    const inKey = (s: SessionInfo) => normalizeProfileKey(s.profile) === key
    const loaded = $sessions.get().filter(inKey).length

    const result = await listAllProfileSessions(SIDEBAR_SESSIONS_INITIAL_LIMIT, 1, 'exclude', 'recent', key, {
      excludeSources: SIDEBAR_EXCLUDED_SOURCES,
      offset: loaded
    })

    if (gatewayActivationEpoch() !== epoch || sidebarProfileForScope(profileScopeRef.current) !== ownerScope
      || refreshSessionsRequestRef.current !== requestId || result.errors?.length
      || result.sessions.some(row => normalizeProfileKey(row.profile) !== key)) return

    setSessions(prev => {
      const previousForProfile = prev.filter(inKey)
      const keep = sessionsToKeep(key)

      for (const session of previousForProfile) {
        keep.add(session.id)
      }

      return [...prev.filter(s => !inKey(s)), ...mergeSessionPage(dropTombstoned(previousForProfile), dropTombstoned(result.sessions), keep)]
    })

    const total = result.profile_totals?.[key] ?? result.total ?? result.sessions.length
    setSessionProfileTotals(prev => ({ ...prev, [key]: Math.max(total, loaded + result.sessions.length) }))
  }, [])

  // A filter searches the loaded page, so switching one on has to deepen the
  // page — otherwise "merged PRs" answers for the last 50 rows and reads as
  // "you only have 6 merged PRs". Clearing the filters hands the window back:
  // the list refreshes on every settled turn, and paying for 300 rows a turn
  // once the view is unfiltered again buys nothing. Whatever the user had
  // paged to by hand is what it returns to.
  const unfilteredLimit = useRef<null | number>(null)

  useEffect(
    () =>
      $sidebarFiltersActive.subscribe(active => {
        if (active) {
          unfilteredLimit.current ??= $sessionsLimit.get()

          if (raiseSessionsLimit(SIDEBAR_FILTERED_PAGE_SIZE)) {
            void refreshSessions()
          }
        } else if (unfilteredLimit.current !== null) {
          const restored = unfilteredLimit.current
          unfilteredLimit.current = null

          if ($sessionsLimit.get() > restored) {
            $sessionsLimit.set(restored)
            void refreshSessions()
          }
        }
      }),
    [refreshSessions]
  )

  return {
    loadMoreMessagingForPlatform,
    loadMoreSessions,
    loadMoreSessionsForProfile,
    refreshCronJobs,
    refreshMessagingSessions,
    refreshSessions
  }
}
