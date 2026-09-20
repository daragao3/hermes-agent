/**
 * Keep a dead stdio pipe from surfacing as a main-process fault.
 *
 * The Desktop app is launched with stdout/stderr redirected (to desktop.log,
 * or to a parent that may go away). On Windows, Node backs a redirected
 * stdio fd with a `SyncWriteStream`, whose `_write` calls `fs.writeSync`
 * DIRECTLY — so when the far end of that pipe closes, the EPIPE is thrown
 * SYNCHRONOUSLY, straight out through `Writable.write` and into whatever
 * called `console.*`. It is not emitted as an `'error'` event, so the usual
 * `process.stdout.on('error', ...)` guard never sees it.
 *
 * That matters because the caller is frequently not ours. Measured
 * 2026-09-19T15:15:17Z: a box-wide kill sweep terminated 16+ processes with
 * 0x40010004 (DBG_TERMINATE_PROCESS) in ~600ms, taking the Hermes backend
 * with it. Electron's own internals then reported the resulting IPC failures
 * through `replyWithError`, which calls `console.error` — and each of those
 * calls threw EPIPE, producing NINE `[main] Uncaught exception` records in
 * three seconds:
 *
 *     at writeSync (node:fs:917:3)
 *     at SyncWriteStream._write (node:internal/fs/sync_write_stream:27:5)
 *     ...
 *     at console.error (node:internal/console/constructor:444:26)
 *     at replyWithError (node:electron/js2c/browser_init:2:114880)
 *
 * The app survived (Electron installs its own `uncaughtException` listener),
 * so this is a robustness and signal-to-noise defect rather than a crash —
 * but it is a real one on both counts. A broken LOG pipe is not a program
 * error: nothing is wrong except that nobody is reading. Reporting it as a
 * main-process fault buries genuine faults in `desktop.log`, and it does so
 * exactly when something has already gone wrong and the log matters most.
 *
 * Nothing is lost by swallowing these. The pipe is already closed, so the
 * write had nowhere to go either way; `desktop.log` is written through
 * `rememberLog`, a separate file path that is unaffected (it kept working
 * throughout the 15:15:17Z storm, which is how the EPIPEs came to be
 * recorded at all).
 */

/** Errors that mean "the far end is gone", not "the program is wrong". */
const BROKEN_PIPE_CODES = new Set(['EPIPE', 'ERR_STREAM_DESTROYED', 'ERR_STREAM_WRITE_AFTER_END'])

export interface WritableLike {
  write: (...args: unknown[]) => unknown
}

export interface StdioResilienceOptions {
  /** Defaults to the real stdout/stderr. */
  streams?: WritableLike[]
  /**
   * Called once per stream the first time a broken-pipe write is swallowed,
   * so the condition is observable without re-entering the broken stream.
   * Must not write to the guarded streams.
   */
  onBrokenPipe?: (code: string) => void
}

/** True for a synchronous broken-pipe throw from a stdio write. */
export function isBrokenPipeError(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false
  }

  const code = (error as { code?: unknown }).code

  return typeof code === 'string' && BROKEN_PIPE_CODES.has(code)
}

/**
 * Wrap `write` on each stream so a broken-pipe throw is swallowed.
 *
 * Returns a function that restores the original `write` implementations —
 * used by tests, and by any caller that needs the raw streams back.
 *
 * Idempotent: a stream already guarded is left alone, so a double install
 * cannot build a chain of wrappers that each swallow the same error.
 */
export function installStdioResilience({
  streams,
  onBrokenPipe
}: StdioResilienceOptions = {}): () => void {
  const targets = streams ?? [process.stdout as unknown as WritableLike, process.stderr as unknown as WritableLike]
  const restores: Array<() => void> = []

  for (const stream of targets) {
    if (!stream || typeof stream.write !== 'function') {
      continue
    }

    const existing = stream.write as { __hermesStdioGuard?: true }

    if (existing.__hermesStdioGuard) {
      continue
    }

    // Keep the ORIGINAL reference for restore and the bound copy for calling.
    // Restoring the bound copy would leave a different function identity in
    // place, so `restore()` would not actually undo the install.
    const original = stream.write
    const invoke = original.bind(stream)
    let reported = false

    const guarded = (...args: unknown[]) => {
      try {
        return invoke(...args)
      } catch (error) {
        if (!isBrokenPipeError(error)) {
          throw error
        }

        if (!reported) {
          reported = true

          try {
            onBrokenPipe?.((error as { code: string }).code)
          } catch {
            // A reporter that throws must not resurrect the fault we just
            // suppressed — this path exists precisely to stop throwing.
          }
        }

        // Report the write as accepted. The caller is console.*, which has
        // no failure handling to offer anyway, and backpressure on a pipe
        // nobody is reading is meaningless.
        return true
      }
    }

    guarded.__hermesStdioGuard = true as const
    stream.write = guarded as unknown as WritableLike['write']
    restores.push(() => {
      stream.write = original as unknown as WritableLike['write']
    })
  }

  return () => {
    for (const restore of restores) {
      restore()
    }
  }
}
