import { useStore } from '@nanostores/react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionListActions } from '@/app/session/hooks/use-session-list-actions'
import type * as HermesModule from '@/hermes'
import { $desktopBoot } from '@/store/boot'
import { closeSecondaryGateways } from '@/store/gateway'
import { $activeGatewayProfile, $profileScope, $showAllProfiles } from '@/store/profile'
import { $connection, $gatewayState, $sessions, setSessions } from '@/store/session'

import { useGatewayBoot } from './use-gateway-boot'
import { takeGatewaySurvivor } from './gateway-hmr-survivor'

// Locks the boot seam between profile adoption and the first session fetch.
//
// $profileScope (which the sidebar FILTERS rows by) is derived from
// $activeGatewayProfile, and boot sets that from the Electron profile
// preference in adoptPrimaryProfile(). refreshSessions() reads the same scope
// to decide which profile to FETCH. If boot ever stops awaiting adoption before
// invoking the refresh callback, the callback it took from the last committed
// render still closes over the pre-adoption scope: the fetch asks for the old
// profile while the sidebar filters by the new one, and every row is dropped.
// Nothing re-runs the fetch on a scope change, so that state is permanent.
//
// Mutation-proven: replacing `await adoptPrimaryProfile()` with
// `void adoptPrimaryProfile()` in use-gateway-boot fails the first test with
// exactly that symptom ("expected [ 'default' ] to include 'main'").
//
// NOTE this is NOT the cause of the 2026-09-07 profile-switch sidebar blackout
// (loops profilescope-forwarding-platform-audit-20260907). That was measured to
// the backend: profile 'main' holds only cron/subagent/messaging sessions, all
// of which the recents slice excludes by source, so scoping to it returns a
// genuinely empty recents list. This file only guards the seam next to it.
//
// Only the sidebar slice is faked; the socket is faked as in
// use-gateway-boot.test.tsx.

const listSidebarSessions = vi.fn(async (req: { recentsProfile: string }) => ({
  cron: { sessions: [] },
  errors: [],
  messaging: { sessions: [] },
  recents: {
    profile_matched: true,
    profile_totals: { [req.recentsProfile]: 1 },
    sessions: [
      {
        id: `session-of-${req.recentsProfile}`,
        message_count: 3,
        profile: req.recentsProfile,
        source: 'desktop',
        started_at: 1,
        last_active: 1
      }
    ],
    total: 1
  }
}))

vi.mock('@/hermes', async importOriginal => {
  const actual = await importOriginal<typeof HermesModule>()

  return {
    ...actual,
    // { jobs, errors } since the endpoint gained an errors channel; a bare
    // array here makes refreshCronJobs set the atom to undefined.
    getCronJobs: vi.fn(async () => ({ errors: [], jobs: [] })),
    listAllProfileSessions: vi.fn(async () => ({ errors: [], profile_totals: {}, sessions: [], total: 0 })),
    listSidebarSessions: (req: { recentsProfile: string }) => listSidebarSessions(req)
  }
})

type Listener = (ev: unknown) => void

class FakeWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static instances: FakeWebSocket[] = []

  readyState = 0
  private listeners: Record<string, Set<Listener>> = {}

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN
      this.emit('open', {})
    }, 0)
  }

  addEventListener(type: string, fn: Listener) {
    ;(this.listeners[type] ??= new Set()).add(fn)
  }

  removeEventListener(type: string, fn: Listener) {
    this.listeners[type]?.delete(fn)
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    this.emit('close', {})
  }

  private emit(type: string, ev: unknown) {
    for (const fn of this.listeners[type] ?? []) {
      fn(ev)
    }
  }
}

function fakeDesktop(profile: null | string) {
  const conn = {
    authMode: 'token' as const,
    baseUrl: 'http://127.0.0.1:1234',
    profile: profile ?? 'default',
    token: 't',
    wsUrl: 'ws://127.0.0.1:1234/api/ws?token=t'
  }

  return {
    getBootProgress: vi.fn(async () => ({
      error: null,
      fakeMode: false,
      message: '',
      phase: 'init',
      progress: 0,
      running: true,
      timestamp: Date.now()
    })),
    getConnection: vi.fn(async () => conn),
    getGatewayWsUrl: vi.fn(async () => conn.wsUrl),
    onBackendExit: vi.fn(() => () => undefined),
    onBootProgress: vi.fn(() => () => undefined),
    onConnectionApplied: vi.fn(() => () => undefined),
    onPowerResume: vi.fn(() => () => undefined),
    onWindowStateChanged: vi.fn(() => () => undefined),
    profile: { get: vi.fn(async () => ({ profile })) },
    touchBackend: vi.fn(async () => undefined)
  }
}

// The real wiring: the sidebar's profile scope feeds useSessionListActions, and
// the resulting refreshSessions is handed to useGatewayBoot (wiring.tsx).
function Harness() {
  const profileScope = useStore($profileScope)
  const { refreshSessions } = useSessionListActions({ profileScope })

  useGatewayBoot({
    beforeConnectionSwitch: () => undefined,
    handleGatewayEvent: () => undefined,
    onConnectionReady: () => undefined,
    onGatewayReady: () => undefined,
    refreshHermesConfig: async () => undefined,
    refreshSessions
  })

  return null
}

const originalWebSocket = globalThis.WebSocket

function closeFixtureGateways() {
  // Vitest enables the real HMR survivor path; each test owns a fresh fake socket.
  takeGatewaySurvivor()?.gateway.close()
  closeSecondaryGateways()
  $connection.set(null)
}

beforeEach(() => {
  closeFixtureGateways()
  vi.useFakeTimers()
  listSidebarSessions.mockClear()
  FakeWebSocket.instances = []
  ;(globalThis as { WebSocket: unknown }).WebSocket = FakeWebSocket
  $gatewayState.set('idle')
  $showAllProfiles.set(false)
  $activeGatewayProfile.set('default')
  setSessions([])
  $desktopBoot.set({
    error: null,
    fakeMode: false,
    message: '',
    phase: 'init',
    progress: 0,
    running: true,
    timestamp: Date.now(),
    visible: true
  })
})

afterEach(() => {
  cleanup()
  closeFixtureGateways()
  vi.useRealTimers()
  ;(globalThis as { WebSocket: unknown }).WebSocket = originalWebSocket
  delete (window as { hermesDesktop?: unknown }).hermesDesktop
})

async function flushAsync() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

describe('boot profile adoption keeps the session fetch and the sidebar filter on the same scope', () => {
  it('adopting a NAMED profile refetches recents for that profile, so the scoped sidebar is not empty', async () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = fakeDesktop('main')

    render(<Harness />)
    await flushAsync()

    // The scope the sidebar filters by after adoption.
    expect($profileScope.get()).toBe('main')

    // At least one fetch must have asked for that same scope. Without it the
    // only rows in the store are the previous scope's and the sidebar filter
    // (normalizeProfileKey(s.profile) === profileScope) drops every one.
    const scopes = listSidebarSessions.mock.calls.map(([req]) => req.recentsProfile)

    expect(scopes).toContain('main')

    // The end state that actually matters: rows the sidebar can render.
    expect($sessions.get().filter(s => s.profile === 'main').length).toBeGreaterThan(0)
  })

  it('no preference (default profile) still fetches exactly once for the default scope', async () => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = fakeDesktop(null)

    render(<Harness />)
    await flushAsync()

    expect($profileScope.get()).toBe('default')

    const scopes = listSidebarSessions.mock.calls.map(([req]) => req.recentsProfile)

    expect(scopes).toEqual(['default'])
  })
})
