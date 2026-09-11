import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createCronJob,
  deleteCronJob,
  getCronJob,
  getCronJobRuns,
  getCronJobs,
  pauseCronJob,
  resumeCronJob,
  setApiRequestConnection,
  setApiRequestProfile,
  triggerCronJob,
  updateCronJob
} from './hermes'

// Contract: every cron helper must carry the active gateway profile, so a
// multi-profile / remote user's cron list, runs, and mutations hit the backend
// they're actually on — not the primary/default. Without it, selecting a remote
// profile still showed the local primary's jobs (the "remote cron jobs don't
// show up" bug), the counterpart to the backend-action-helper fix in
// hermes-profile-scope.test.ts.
describe('cron helpers are profile-scoped', () => {
  const api = vi.fn(async (_req: { path: string; profile?: string }) => ({}) as never)

  beforeEach(() => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { api }
    api.mockClear()
  })

  afterEach(() => {
    setApiRequestProfile(null)
    setApiRequestConnection(null)
    delete (window as { hermesDesktop?: unknown }).hermesDesktop
  })

  const lastProfile = () => api.mock.calls.at(-1)?.[0].profile

  it('omits profile when none is active (single-profile users unaffected)', () => {
    void getCronJobs()
    expect(lastProfile()).toBeUndefined()
  })

  it('forwards the active profile to every cron helper', () => {
    setApiRequestProfile('coder')

    void getCronJobs()
    void getCronJob('job-1')
    void getCronJobRuns('job-1')
    void createCronJob({ name: 'nightly', prompt: 'run', schedule: '0 3 * * *' } as never)
    void updateCronJob('job-1', { enabled: false } as never)
    void pauseCronJob('job-1')
    void resumeCronJob('job-1')
    void triggerCronJob('job-1')
    void deleteCronJob('job-1')

    for (const call of api.mock.calls) {
      expect(call[0].profile).toBe('coder')
    }
  })

  it('runs key off the OWNING profile, not the ambient scope', () => {
    // Regression: run history sent only profileScoped() -- the sidebar's ambient
    // profile -- so a job listed from the cross-profile aggregate had its runs
    // looked up against whatever profile the UI happened to be showing. The
    // panel's catch renders a failed/empty result as "No runs yet", so a
    // wrongly-scoped lookup was indistinguishable from a job that never ran.
    setApiRequestProfile('default')

    void getCronJobRuns('job-1', 5, 'main')

    expect(api.mock.calls.at(-1)?.[0].profile).toBe('main')
    expect(api.mock.calls.at(-1)?.[0].path).toBe('/api/cron/jobs/job-1/runs?limit=5&profile=main')
  })

  it('falls back to the ambient route when a job carries no owning profile', () => {
    setApiRequestProfile('coder')

    void getCronJobRuns('job-1', 5)

    expect(api.mock.calls.at(-1)?.[0].profile).toBe('coder')
    expect(api.mock.calls.at(-1)?.[0].path).toBe('/api/cron/jobs/job-1/runs?limit=5')
  })
  it('omits connectionId when the local pool serves the active gateway', () => {
    void getCronJobRuns('job-1')
    expect(api.mock.calls.at(-1)?.[0]).not.toHaveProperty('connectionId')
  })

  // Contract: with a registered gateway connection active, cron run sessions
  // live in THAT gateway's state.db — not in any local profile's. Every cron
  // helper must tag the owning connection so the main process routes the REST
  // call to the same backend the job list (and its runs) actually live on.
  // Without it, run history read a local state.db with zero cron rows and
  // every job showed "No runs yet" (#87882).
  it('forwards the active registry connection to every cron helper', () => {
    setApiRequestProfile('research')
    setApiRequestConnection('gw-tailscale')

    void getCronJobs('research')
    void getCronJob('job-1')
    void getCronJobRuns('job-1')
    void createCronJob({ name: 'nightly', prompt: 'run', schedule: '0 3 * * *' } as never)
    void updateCronJob('job-1', { enabled: false } as never)
    void pauseCronJob('job-1')
    void resumeCronJob('job-1')
    void triggerCronJob('job-1')
    void deleteCronJob('job-1')

    for (const call of api.mock.calls) {
      expect((call[0] as { connectionId?: string }).connectionId).toBe('gw-tailscale')
      expect(call[0].profile).toBe('research')
    }
  })

  it('list accepts an explicit ?profile= for endpoint-level filtering', () => {
    // profileScoped() routes the backend process; the list endpoint ALSO
    // aggregates 'all' by default, so callers pass an explicit profile to
    // filter what the endpoint returns (sidebar / cron overlay scoping).
    void getCronJobs('worker_alpha')
    expect(api.mock.calls.at(-1)?.[0].path).toBe('/api/cron/jobs?profile=worker_alpha')

    void getCronJobs('all')
    expect(api.mock.calls.at(-1)?.[0].path).toBe('/api/cron/jobs?profile=all')

    // Omitting the arg keeps the legacy unfiltered path.
    void getCronJobs()
    expect(api.mock.calls.at(-1)?.[0].path).toBe('/api/cron/jobs')
  })
})

// A partial cross-profile failure and an empty crontab are different facts.
// The endpoint reports the first as { jobs, errors }; the client must preserve
// that distinction rather than handing callers a bare row list, and must still
// work against a gateway that predates the shape (the packaged renderer and the
// gateway are deployed independently, so either can be the older half).
describe('getCronJobs normalizes the list response', () => {
  const api = vi.fn()

  beforeEach(() => {
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = { api }
    api.mockReset()
  })

  afterEach(() => {
    setApiRequestProfile(null)
    delete (window as { hermesDesktop?: unknown }).hermesDesktop
  })

  it('carries per-profile read failures through to the caller', async () => {
    api.mockResolvedValue({
      jobs: [{ enabled: true, id: 'job-1' }],
      errors: [{ profile: 'matcher', error: 'no such table: sessions' }]
    })

    const listing = await getCronJobs('all')

    expect(listing.jobs).toHaveLength(1)
    expect(listing.errors).toEqual([{ profile: 'matcher', error: 'no such table: sessions' }])
  })

  it('reports no errors when every profile answered', async () => {
    api.mockResolvedValue({ jobs: [{ enabled: true, id: 'job-1' }], errors: [] })

    expect((await getCronJobs('all')).errors).toEqual([])
  })

  it('accepts a pre-{jobs,errors} backend answering with a bare array', async () => {
    api.mockResolvedValue([{ enabled: true, id: 'job-1' }])

    const listing = await getCronJobs('all')

    expect(listing.jobs).toHaveLength(1)
    expect(listing.errors).toEqual([])
  })
})
