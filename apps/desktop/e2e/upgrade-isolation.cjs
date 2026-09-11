// Loaded before the packaged entry point; only host-facing fixture boundaries are replaced.
const fs = require('node:fs')
const electron = require('electron')
const childProcess = require('node:child_process')
const { syncBuiltinESMExports } = require('node:module')
const remote = process.env.HERMES_UPGRADE_REMOTE_URL
const isolatedRemote = remote && new URL(remote).hostname === '127.0.0.1' && new URL(remote).protocol === 'http:'
if (!process.env.HERMES_UPGRADE_ISOLATION_RECEIPT || (!process.env.HERMES_DESKTOP_BOOT_FAKE_ERROR && !isolatedRemote)) {
  throw new Error('Upgrade isolation requires its receipt and controlled boot failure')
}
const receipt = { protocolCalls: 0, childCalls: [] }
const save = () => fs.writeFileSync(process.env.HERMES_UPGRADE_ISOLATION_RECEIPT, JSON.stringify(receipt))
electron.app.setAsDefaultProtocolClient = () => { receipt.protocolCalls++; save(); return true }
electron.app.setLoginItemSettings = () => {}
electron.globalShortcut.register = () => true
electron.globalShortcut.unregister = () => {}
electron.globalShortcut.unregisterAll = () => {}
electron.BrowserWindow.prototype.show = () => {}
electron.BrowserWindow.prototype.showInactive = () => {}
electron.BrowserWindow.prototype.focus = () => {}
for (const name of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) {
  childProcess[name] = (...args) => {
    receipt.childCalls.push({ name, command: String(args[0]) }); save()
    throw new Error('Upgrade fixture forbids child processes: ' + name)
  }
}
// Observe transport timing without changing requests, headers, bodies, or timeouts.
if (isolatedRemote) {
  const http = require('node:http')
  const original = http.request
  let sequence = 0
  http.request = function (...args) {
    const request = original.apply(this, args)
    const id = ++sequence
    const started = Date.now()
    const record = (event, extra = {}) => fs.appendFileSync(
      process.env.HERMES_UPGRADE_ISOLATION_RECEIPT + '.http.jsonl',
      JSON.stringify({ id, event, path: request.path, elapsedMs: Date.now() - started, ...extra }) + '\n')
    record('start')
    request.on('response', response => {
      record('response', { status: response.statusCode })
      response.on('end', () => record('end'))
    })
    request.on('timeout', () => record('timeout'))
    request.on('error', error => record('error', { code: error.code }))
    return request
  }
}
syncBuiltinESMExports()
save()
