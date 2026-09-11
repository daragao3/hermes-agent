import { type CronJob, type CronProfileError, getApiRequestConnection, getCronJobs, triggerCronJob } from '@/hermes'
import {
  beginCronJobsAction,
  beginCronJobsRequest,
  commitCronJobsRequest,
  type CronJobsRequest,
  isCronJobsRequestCurrent,
  isCronJobsScopeCurrent
} from '@/store/cron'
import { cronListScope } from '@/store/profile'

export interface CronTriggerRefreshResult {
  jobs: CronJob[] | null
  refreshError: unknown | null
  stale: boolean
  profileErrors?: CronProfileError[]
}

export interface CronMutationRefreshResult<T> extends CronTriggerRefreshResult {
  value: T | null
}

function cronRequestScope(profile: string): string {
  return `${getApiRequestConnection() ?? ''}\u0000${profile}`
}

async function refreshForGeneration(profile: string, request: CronJobsRequest): Promise<CronTriggerRefreshResult> {
  try {
    const listing = await getCronJobs(cronListScope(profile))
    const jobs = listing.jobs

    if (!commitCronJobsRequest(request, jobs)) {
      return { jobs: null, refreshError: null, stale: true }
    }

    const refreshError = listing.errors.length
      ? new Error(`Could not read cron profiles: ${listing.errors.map(error => error.profile).join(', ')}`)
      : null
    return { jobs, refreshError, stale: false, ...(listing.errors.length ? { profileErrors: listing.errors } : {}) }
  } catch (refreshError) {
    if (!isCronJobsRequestCurrent(request)) {
      return { jobs: null, refreshError: null, stale: true }
    }

    return { jobs: null, refreshError, stale: false }
  }
}

export function refreshCronJobs(profile: string): Promise<CronTriggerRefreshResult> {
  return refreshForGeneration(profile, beginCronJobsRequest(cronRequestScope(profile)))
}

export async function mutateAndRefreshCronJobs<T>(
  profile: string,
  mutate: () => Promise<T>
): Promise<CronMutationRefreshResult<T>> {
  const scopeToken = beginCronJobsAction(cronRequestScope(profile))
  let value: T

  try {
    value = await mutate()
  } catch (mutationError) {
    if (!isCronJobsScopeCurrent(scopeToken)) {
      return { jobs: null, refreshError: null, stale: true, value: null }
    }

    throw mutationError
  }

  if (!isCronJobsScopeCurrent(scopeToken)) {
    return { jobs: null, refreshError: null, stale: true, value: null }
  }

  const refreshed = await refreshCronJobs(profile)

  if (!isCronJobsScopeCurrent(scopeToken)) {
    return { jobs: null, refreshError: null, stale: true, value: null }
  }

  // A newer request in the same scope may supersede this refresh after the
  // mutation itself has already succeeded. Preserve the mutation result so
  // callers can settle dialogs/toasts without publishing the older snapshot.
  if (refreshed.stale) {
    return { jobs: null, refreshError: null, stale: false, value }
  }

  return { ...refreshed, value }
}

/**
 * Trigger a job synchronously, then replace the local view from the backend.
 * A completed one-shot may have been deleted, so the trigger response alone is
 * not an authoritative list update. Refresh failure is reported separately:
 * the trigger already succeeded and must not be shown as failed.
 */
export async function triggerAndRefreshCronJobs(
  jobId: string,
  profile: 'all' | string
): Promise<CronTriggerRefreshResult> {
  const { value: _value, ...result } = await mutateAndRefreshCronJobs(profile, () => triggerCronJob(jobId))

  return result
}
