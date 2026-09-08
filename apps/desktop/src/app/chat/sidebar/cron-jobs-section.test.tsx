// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CronJob } from '@/types/hermes'

import { SidebarCronJobsSection } from './cron-jobs-section'

// The sidebar's inline run peek had the same defect as the cron panel: the
// catch wrote [] into the runs state, so a rejected request rendered as
// "No runs yet" — the same confident empty state that made the 2026-09-07
// profile-scope bugs expensive to diagnose. Failed and empty must stay
// distinct here too.

const getCronJobRuns = vi.fn()

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getCronJobRuns: (...args: unknown[]) => getCronJobRuns(...args)
}))

const job: CronJob = {
  enabled: true,
  id: 'job-1',
  name: 'nightly-sweep',
  profile: 'main',
  state: 'scheduled'
} as CronJob

async function renderSection() {
  await act(async () => {
    render(
      <SidebarCronJobsSection
        jobs={[job]}
        label="Cron jobs"
        onManageJob={vi.fn()}
        onOpenRun={vi.fn()}
        onToggle={vi.fn()}
        onTriggerJob={vi.fn()}
        open
      />
    )
  })
}

/** Expand the inline run peek for the single job. */
async function openThePeek() {
  const toggle = await screen.findByLabelText('Show runs')
  await act(async () => {
    fireEvent.click(toggle)
  })
}

beforeEach(() => {
  getCronJobRuns.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('sidebar cron run peek distinguishes failed from empty', () => {
  it('says "No runs yet" when the request succeeded and returned nothing', async () => {
    await renderSection()
    await openThePeek()

    expect(await screen.findByText('No runs yet')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('reports the failure instead of claiming the job has never run', async () => {
    getCronJobRuns.mockRejectedValue(new Error('no such table: sessions'))

    await renderSection()
    await openThePeek()

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain('Run history failed to load')
    expect(screen.queryByText('No runs yet')).toBeNull()
  })

  it('retry re-issues the request and clears the failed state', async () => {
    getCronJobRuns.mockRejectedValueOnce(new Error('backend down'))
    getCronJobRuns.mockResolvedValue([])

    await renderSection()
    await openThePeek()

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    })

    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(await screen.findByText('No runs yet')).toBeTruthy()
  })
})
