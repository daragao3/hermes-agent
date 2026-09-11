// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CronJob } from '@/types/hermes'

import { CronView } from './index'

// A FAILED request and an EMPTY result are different facts, and this panel used
// to render them identically. `getCronJobRuns`'s catch wrote [] into the runs
// state, which falls straight through to "No runs yet"; the list's aggregate
// dropped a per-profile read failure inside the backend and rendered the
// survivors as if they were the whole crontab. Three separate profile-scope
// bugs (2026-09-07) each reached the user as a confident empty state, and hours
// went into inferring mechanisms a visible error would have settled in one
// step. These tests are the behaviour claim that the two states stay distinct.

const getCronJobs = vi.fn()
const getCronJobRuns = vi.fn()

// Partial mock: store/profile.ts subscribes setApiRequestProfile at import
// time, so a bare factory breaks the module graph before any test runs.
vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getCronJobRuns: (...args: unknown[]) => getCronJobRuns(...args),
  getCronJobs: (...args: unknown[]) => getCronJobs(...args)
}))

vi.mock('@/store/notifications', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  notify: vi.fn(),
  notifyError: vi.fn()
}))

vi.mock('@/lib/model-options', () => ({
  requestModelOptions: vi.fn(async () => [])
}))

const job = (patch: Partial<CronJob> = {}): CronJob =>
  ({
    enabled: true,
    id: 'job-1',
    name: 'nightly-sweep',
    profile: 'main',
    schedule: { display: 'Every day at 9:00 AM', expr: '0 9 * * *' },
    state: 'scheduled',
    ...patch
  }) as CronJob

async function renderCron() {
  // The editor dialog runs a useQuery for model options; it is mounted by the
  // panel regardless of whether it is open.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let result: ReturnType<typeof render>
  await act(async () => {
    result = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CronView onClose={vi.fn()} setStatusbarItemGroup={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>
    )
  })

  return result!
}

/** Open the one job so its detail pane (and run history) mounts. The name
 *  appears in both the list row and the detail header, so click the first. */
async function openTheJob() {
  const rows = await screen.findAllByText('nightly-sweep')
  await act(async () => {
    fireEvent.click(rows[0])
  })
}

beforeEach(() => {
  getCronJobs.mockResolvedValue({ jobs: [job()], errors: [] })
  getCronJobRuns.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('cron run history distinguishes a failed request from an empty history', () => {
  it('says "No runs yet" only when the request SUCCEEDED and returned nothing', async () => {
    getCronJobRuns.mockResolvedValue([])

    await renderCron()
    await openTheJob()

    expect(await screen.findByText('No runs yet')).toBeTruthy()
    expect(screen.queryByText(/Run history failed to load/)).toBeNull()
  })

  it('names the failure instead of claiming the job has never run', async () => {
    getCronJobRuns.mockRejectedValue(new Error('no such table: sessions'))

    await renderCron()
    await openTheJob()

    // The whole point: the panel must NOT say "No runs yet" here.
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain('Run history failed to load')
    expect(screen.getByRole('alert').textContent).toContain('no such table: sessions')
    expect(screen.queryByText('No runs yet')).toBeNull()
  })

  it('retry re-issues the request and clears the failed state on success', async () => {
    getCronJobRuns.mockRejectedValueOnce(new Error('backend down'))
    getCronJobRuns.mockResolvedValue([])

    await renderCron()
    await openTheJob()

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    })

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(await screen.findByText('No runs yet')).toBeTruthy()
  })
})

describe('cron list distinguishes a partial aggregate failure from an empty crontab', () => {
  it('names the profiles that could not be read', async () => {
    getCronJobs.mockResolvedValue({
      jobs: [job()],
      errors: [{ profile: 'matcher', error: 'no such table: sessions' }]
    })

    await renderCron()

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Some jobs could not be read')
    expect(alert.textContent).toContain('matcher')
  })

  it('does NOT show the "no jobs yet" empty state when every profile failed', async () => {
    // Zero rows + a read failure is a BROKEN list, not an empty one. Rendering
    // the create-your-first-job empty state over it is the exact lie this whole
    // change exists to stop.
    getCronJobs.mockResolvedValue({
      jobs: [],
      errors: [{ profile: 'main', error: 'jobs.json is locked' }]
    })

    await renderCron()

    expect((await screen.findByRole('alert')).textContent).toContain('main')
    expect(screen.queryByText('No scheduled jobs yet')).toBeNull()
  })

  it('still shows the empty state when the list genuinely came back empty', async () => {
    getCronJobs.mockResolvedValue({ jobs: [], errors: [] })

    await renderCron()

    expect(await screen.findByText('No scheduled jobs yet')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
