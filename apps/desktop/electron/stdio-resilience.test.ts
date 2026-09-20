/**
 * A dead stdio pipe must not surface as a main-process fault.
 *
 * Measured 2026-09-19T15:15:17Z: a box-wide kill sweep terminated 16+
 * processes with 0x40010004 (DBG_TERMINATE_PROCESS) in ~600ms, taking the
 * Hermes backend with it (Security 4689: 4x Hermes.exe, 3x python.exe, 5x
 * python3.11.exe). Electron then reported the resulting IPC failures through
 * its internal `replyWithError`, which calls `console.error` — and on Windows
 * a redirected stdout/stderr is a `SyncWriteStream` whose `_write` calls
 * `fs.writeSync` directly, so the EPIPE came back as a SYNCHRONOUS throw:
 *
 *     at writeSync (node:fs:917:3)
 *     at SyncWriteStream._write (node:internal/fs/sync_write_stream:27:5)
 *     at Writable.write (node:internal/streams/writable:508:10)
 *     at console.error (node:internal/console/constructor:444:26)
 *     at replyWithError (node:electron/js2c/browser_init:2:114880)
 *
 * Nine `[main] Uncaught exception` records in three seconds, none describing
 * a real program error. Because the throw is synchronous rather than an
 * emitted `'error'` event, a `process.stdout.on('error', ...)` guard does not
 * see it — which is why this wraps `write` instead.
 */
import { describe, expect, it, vi } from 'vitest'

import { installStdioResilience, isBrokenPipeError } from './stdio-resilience'

/** A stream whose write throws synchronously, like SyncWriteStream on EPIPE. */
const throwingStream = (code: string) => {
  const error = Object.assign(new Error(`${code}: broken pipe, write`), { code })

  return {
    write: vi.fn(() => {
      throw error
    })
  }
}

const okStream = () => ({ write: vi.fn(() => true) })

describe('isBrokenPipeError', () => {
  it('recognises the codes that mean "nobody is reading"', () => {
    expect(isBrokenPipeError({ code: 'EPIPE' })).toBe(true)
    expect(isBrokenPipeError({ code: 'ERR_STREAM_DESTROYED' })).toBe(true)
    expect(isBrokenPipeError({ code: 'ERR_STREAM_WRITE_AFTER_END' })).toBe(true)
  })

  it('does not swallow unrelated failures', () => {
    // ENOSPC is a real problem and must keep propagating; treating every
    // write failure as a broken pipe would hide a full disk.
    expect(isBrokenPipeError({ code: 'ENOSPC' })).toBe(false)
    expect(isBrokenPipeError(new TypeError('not a stream'))).toBe(false)
    expect(isBrokenPipeError(null)).toBe(false)
    expect(isBrokenPipeError(undefined)).toBe(false)
    expect(isBrokenPipeError('EPIPE')).toBe(false)
    expect(isBrokenPipeError({ code: 123 })).toBe(false)
  })
})

describe('installStdioResilience', () => {
  it('swallows a synchronous EPIPE and reports the write as accepted', () => {
    const stream = throwingStream('EPIPE')

    installStdioResilience({ streams: [stream] })

    // The whole point: this call threw before the fix.
    expect(() => stream.write('boom\n')).not.toThrow()
    expect(stream.write('boom\n')).toBe(true)
  })

  it('REGRESSION: a console.error-shaped call site no longer faults', () => {
    // Models the production stack: console.error -> Writable.write -> throw.
    const stream = throwingStream('EPIPE')

    installStdioResilience({ streams: [stream] })

    const consoleErrorLike = (message: string) => stream.write(`${message}\n`)

    expect(() => {
      for (let i = 0; i < 9; i += 1) {
        consoleErrorLike('Error: renderer gone')
      }
    }).not.toThrow()
  })

  it('still throws anything that is not a broken pipe', () => {
    const stream = throwingStream('ENOSPC')

    installStdioResilience({ streams: [stream] })

    expect(() => stream.write('x')).toThrow(/ENOSPC/)
  })

  it('leaves a healthy stream untouched, return value included', () => {
    const stream = okStream()
    // Capture the spy BEFORE install: afterwards `stream.write` is the guard,
    // so asserting on it would test the wrapper rather than the passthrough.
    const spy = stream.write

    installStdioResilience({ streams: [stream] })

    expect(stream.write('hello')).toBe(true)
    expect(spy).toHaveBeenCalledWith('hello')
  })

  it('forwards every argument to the original write', () => {
    const stream = okStream()
    const spy = stream.write

    installStdioResilience({ streams: [stream] })

    const cb = () => {}
    stream.write('chunk', 'utf8', cb)

    expect(spy).toHaveBeenCalledWith('chunk', 'utf8', cb)
  })

  it('reports the broken pipe exactly ONCE per stream', () => {
    // The condition is worth one line in desktop.log. Nine would reproduce
    // the noise this exists to remove.
    const stream = throwingStream('EPIPE')
    const onBrokenPipe = vi.fn()

    installStdioResilience({ streams: [stream], onBrokenPipe })

    for (let i = 0; i < 9; i += 1) {
      stream.write('x')
    }

    expect(onBrokenPipe).toHaveBeenCalledTimes(1)
    expect(onBrokenPipe).toHaveBeenCalledWith('EPIPE')
  })

  it('survives a reporter that itself throws', () => {
    // The reporter writes to desktop.log. If that path is also broken, the
    // suppression must still hold — resurrecting the fault here would defeat
    // the entire guard at exactly the worst moment.
    const stream = throwingStream('EPIPE')

    installStdioResilience({
      streams: [stream],
      onBrokenPipe: () => {
        throw new Error('desktop.log is gone too')
      }
    })

    expect(() => stream.write('x')).not.toThrow()
  })

  it('is idempotent — a second install does not double-wrap', () => {
    const stream = throwingStream('EPIPE')

    installStdioResilience({ streams: [stream] })
    const afterFirst = stream.write

    installStdioResilience({ streams: [stream] })

    expect(stream.write).toBe(afterFirst)
  })

  it('restores the original write', () => {
    const stream = throwingStream('EPIPE')
    const original = stream.write

    const restore = installStdioResilience({ streams: [stream] })

    expect(stream.write).not.toBe(original)

    restore()

    expect(stream.write).toBe(original)
    expect(() => stream.write('x')).toThrow(/EPIPE/)
  })

  it('guards each stream independently', () => {
    const out = okStream()
    const err = throwingStream('EPIPE')
    const onBrokenPipe = vi.fn()

    installStdioResilience({ streams: [out, err], onBrokenPipe })

    expect(out.write('fine')).toBe(true)
    expect(() => err.write('broken')).not.toThrow()
    expect(onBrokenPipe).toHaveBeenCalledTimes(1)
  })

  it('skips a stream with no usable write', () => {
    const bogus = { write: undefined } as unknown as { write: (...a: unknown[]) => unknown }

    expect(() => installStdioResilience({ streams: [bogus] })).not.toThrow()
  })

  it('defaults to the real stdout and stderr, and restores them', () => {
    const outBefore = process.stdout.write
    const errBefore = process.stderr.write

    const restore = installStdioResilience()

    expect(process.stdout.write).not.toBe(outBefore)
    expect(process.stderr.write).not.toBe(errBefore)

    restore()

    expect(process.stdout.write).toBe(outBefore)
    expect(process.stderr.write).toBe(errBefore)
  })
})
