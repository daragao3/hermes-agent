import type {
  AutomationBlueprint,
  CronDeliveryTarget,
  CronJob,
  CronJobCreatePayload,
  CronJobUpdates,
  SessionInfo
} from '@/types/hermes'

import { connectionScoped, hermesApi, profileScoped, STARTUP_REQUEST_TIMEOUT_MS } from './client'

// The cron trigger endpoint intentionally waits for the whole job so its
// response reflects the persisted execution result. Agent jobs can run far
// longer than the Electron fetch default; keep this override local to the one
// synchronous long-operation endpoint rather than weakening all API timeouts.
const CRON_TRIGGER_REQUEST_TIMEOUT_MS = 24 * 60 * 60 * 1000

// Cron jobs are stored per-profile (<HERMES_HOME>/cron/jobs.json), and the
// backend's list endpoint defaults to 'all'. Pass a concrete profile key to
// list just that profile's jobs, or 'all' for the unified cross-profile view.
// Omitting the arg keeps the legacy 'all' default for non-profile callers.
// profileScoped() still rides along for backend-process routing.
export function getCronJobs(profile?: string): Promise<CronJob[]> {
  // 'default' is the sentinel normalizeProfileKey() returns when no profile has
  // been explicitly selected -- it means "no preference", NOT the root ~/.hermes
  // profile. The desktop backend honours the sticky ~/.hermes/active_profile and
  // commonly runs as a NAMED profile, so ?profile=default asks for a store that is
  // usually absent, and an absent store is byte-identical to an empty one: the
  // overlay renders "no jobs yet" over a full crontab (measured 2026-09-07:
  // ?profile=default -> 0, ?profile=main -> 85, no scope -> 85). Send no scope and
  // let the endpoint apply its aggregate default. (Literal rather than imported:
  // api/ must not import the store -- see client.ts.)
  const scoped = profile && profile !== 'default' ? profile : ''
  const suffix = scoped ? `?profile=${encodeURIComponent(scoped)}` : ''

  return hermesApi<CronJob[]>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs${suffix}`,
    timeoutMs: STARTUP_REQUEST_TIMEOUT_MS
  })
}

export function getCronJob(jobId: string): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`
  })
}

// `profile`: the job's OWNING profile (CronJob.profile). The list endpoint
// aggregates across profiles, so a job shown under the all-profiles view (or
// under a scope that is not its owner) must have its runs looked up against
// the profile that holds them, never the sidebar's ambient scope -- a
// wrongly-scoped lookup renders as "No runs yet" and is indistinguishable from
// a job that never ran. Omitted, it falls back to the ambient route.
export async function getCronJobRuns(
  jobId: string,
  limit = 20,
  profile?: null | string
): Promise<SessionInfo[]> {
  const suffix = profile ? `&profile=${encodeURIComponent(profile)}` : ''

  const { runs } = await hermesApi<{ runs: SessionInfo[] }>({
    ...(profile ? { profile } : profileScoped()),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/runs?limit=${limit}${suffix}`
  })

  return runs ?? []
}

// The single source of truth for cron delivery targets (local + configured
// gateways). Both the manual cron editor and the blueprint dialog use this so
// they never offer a platform that isn't connected. Mirrors the dashboard.
export async function getCronDeliveryTargets(): Promise<CronDeliveryTarget[]> {
  const { targets } = await hermesApi<{ targets: CronDeliveryTarget[] }>({
    ...profileScoped(),
    ...connectionScoped(),
    path: '/api/cron/delivery-targets'
  })

  return targets ?? []
}

export function createCronJob(body: CronJobCreatePayload): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: '/api/cron/jobs',
    method: 'POST',
    body
  })
}

export function updateCronJob(jobId: string, updates: CronJobUpdates): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`,
    method: 'PUT',
    body: { updates }
  })
}

export function pauseCronJob(jobId: string): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/pause`,
    method: 'POST'
  })
}

export function resumeCronJob(jobId: string): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/resume`,
    method: 'POST'
  })
}

export function triggerCronJob(jobId: string): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}/trigger`,
    method: 'POST',
    timeoutMs: CRON_TRIGGER_REQUEST_TIMEOUT_MS
  })
}

export function deleteCronJob(jobId: string): Promise<{ ok: boolean }> {
  return hermesApi<{ ok: boolean }>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/jobs/${encodeURIComponent(jobId)}`,
    method: 'DELETE'
  })
}

// Automation Blueprints — parameterized cron templates the backend serves from
// cron/blueprint_catalog.py. getAutomationBlueprints returns the gallery
// (deliver options already rewritten to this machine's configured gateways);
// instantiateAutomationBlueprint fills the slots and creates a real cron job via
// the same create_job path as createCronJob.
//
// Profile-scoping is intentionally asymmetric: the GET catalog is global (the
// list endpoint takes no profile — only deliver options are rewritten from the
// configured gateways), so it carries only the profileScoped() header for
// routing. instantiate creates a real per-profile job, so it names the target
// profile explicitly via ?profile=. This mirrors the dashboard's api.ts.
export function getAutomationBlueprints(): Promise<{ blueprints: AutomationBlueprint[] }> {
  return hermesApi<{ blueprints: AutomationBlueprint[] }>({
    ...profileScoped(),
    ...connectionScoped(),
    path: '/api/cron/blueprints',
    timeoutMs: STARTUP_REQUEST_TIMEOUT_MS
  })
}

export function instantiateAutomationBlueprint(
  body: { blueprint: string; values: Record<string, string> },
  profile: string
): Promise<CronJob> {
  return hermesApi<CronJob>({
    ...profileScoped(),
    ...connectionScoped(),
    path: `/api/cron/blueprints/instantiate?profile=${encodeURIComponent(profile)}`,
    method: 'POST',
    body
  })
}
