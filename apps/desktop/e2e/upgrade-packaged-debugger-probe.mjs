import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { chromium, expect } from '@playwright/test'

const output = path.resolve(process.argv[2])
const appRoot = path.resolve(import.meta.dirname, '..')
fs.mkdirSync(output, { recursive: true })
for (const folder of ['home', 'user-data']) fs.mkdirSync(path.join(output, folder))
const receipt = path.join(output, 'isolation.json')
const remoteUrl = process.env.HERMES_UPGRADE_REMOTE_URL
if (remoteUrl) {
  assert.equal(new URL(remoteUrl).hostname, '127.0.0.1')
  assert.equal(new URL(remoteUrl).protocol, 'http:')
  fs.writeFileSync(path.join(output, 'user-data', 'connections.json'), JSON.stringify({
    version: 2, primary: 'fixture', launchMode: 'primary', lastUsed: 'fixture',
    connections: [{ id: 'fixture', kind: 'remote', label: 'Wave 1 fixture', url: remoteUrl,
      authMode: 'token', token: { encoding: 'plain', value: process.env.HERMES_UPGRADE_REMOTE_TOKEN } }],
  }))
}
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !/(_API_KEY|_TOKEN|_SECRET|_PASSWORD|_CREDENTIALS|_ACCESS_KEY|_PRIVATE_KEY|BASE_URL)$/.test(key) &&
  !/^(ELECTRON_|HERMES_DESKTOP_)/.test(key)))
const errorText = 'Upgrade acceptance: isolated backend unavailable'
Object.assign(env, {
  HERMES_HOME: path.join(output, 'home'),
  HERMES_DESKTOP_USER_DATA_DIR: path.join(output, 'user-data'),
  HERMES_DESKTOP_APP_NAME: 'HermesUpgrade-' + Date.now(),
  HERMES_DESKTOP_IGNORE_EXISTING: '1',
  HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '1',
  ...(remoteUrl ? { HERMES_UPGRADE_REMOTE_URL: remoteUrl } : { HERMES_DESKTOP_BOOT_FAKE_ERROR: errorText }),
  HERMES_UPGRADE_ISOLATION_RECEIPT: receipt,
})
const child = spawn(path.join(appRoot, 'release/win-unpacked/Hermes.exe'),
  ['--inspect-brk=127.0.0.1:0', '--remote-debugging-port=0', '--disable-gpu', '--no-sandbox'],
  { cwd: appRoot, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
let logs = ''
for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
  logs += chunk.toString(); fs.appendFileSync(path.join(output, 'electron.log'), chunk)
})
const deadline = (promise, ms, label) => Promise.race([promise, new Promise((_, reject) => {
  const timer = setTimeout(() => reject(new Error('Timeout: ' + label)), ms); timer.unref()
})])
async function captureEvidence(page, name) {
  // DOM evidence is required; a hidden-window compositor capture is supplementary.
  fs.writeFileSync(path.join(output, name + '.html'), await page.content())
  try {
    await page.screenshot({ path: path.join(output, name + '.png'), timeout: 10000 })
  } catch (error) {
    fs.writeFileSync(path.join(output, name + '-screenshot-error.txt'), String(error))
  }
}
async function endpoint(pattern) {
  return deadline(new Promise((resolve, reject) => {
    const interval = setInterval(() => {
      const match = logs.match(pattern)
      if (match) { clearInterval(interval); resolve(match[1]) }
      else if (child.exitCode !== null) { clearInterval(interval); reject(new Error('Electron exited before endpoint')) }
    }, 50)
    interval.unref()
  }), 25000, 'debug endpoint')
}
let socket, browser
try {
  socket = new WebSocket(await endpoint(/Debugger listening on (ws:\/\/[^\s]+)/))
  await deadline(new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject }), 10000, 'inspector connect')
  let sequence = 0
  const pending = new Map()
  let onPause
  const paused = new Promise(resolve => { onPause = resolve })
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data)
    if (message.method === 'Debugger.paused') onPause(message.params)
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id); pending.delete(message.id)
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result)
    }
  }
  const send = (method, params = {}) => deadline(new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params }))
  }), 15000, method)
  await send('Debugger.enable')
  await send('Runtime.runIfWaitingForDebugger')
  const pause = await deadline(paused, 15000, 'pause before entry')
  fs.writeFileSync(path.join(output, 'pause.json'), JSON.stringify(pause, null, 2))
  const shim = path.join(import.meta.dirname, 'upgrade-isolation.cjs')
  const expression = `process.getBuiltinModule('module').createRequire(process.execPath)(${JSON.stringify(shim)}); true`
  const injection = await send('Debugger.evaluateOnCallFrame', { callFrameId: pause.callFrames[0].callFrameId, expression, returnByValue: true })
  fs.writeFileSync(path.join(output, 'injection.json'), JSON.stringify(injection, null, 2))
  assert.equal(injection.exceptionDetails, undefined)
  assert.equal(injection.result.value, true)
  assert.equal(JSON.parse(fs.readFileSync(receipt, 'utf8')).protocolCalls, 0)
  // No app-entry statement may run before the isolation receipt exists.
  await send('Debugger.resume')
  browser = await chromium.connectOverCDP(await endpoint(/DevTools listening on (ws:\/\/[^\s]+)/))
  const context = browser.contexts()[0]
  const page = context.pages()[0] ?? await context.waitForEvent('page', { timeout: 20000 })
  if (remoteUrl) {
    await page.locator('[contenteditable="true"]').first().waitFor({ state: 'attached', timeout: 60000 })
    const connection = await page.evaluate(() => window.hermesDesktop.getConnection())
    assert.equal(connection.baseUrl.replace(/\/$/, ''), remoteUrl)
    fs.writeFileSync(path.join(output, 'connection.json'), JSON.stringify({ baseUrl: connection.baseUrl, profile: connection.profile }))
    if (process.env.HERMES_UPGRADE_CONTRACTS === 'profile-cron') {
      const profiles = await page.evaluate(() => window.hermesDesktop.api({ path: '/api/profiles' }))
      assert(profiles.profiles.some(profile => profile.name === 'wave1-secondary'))
      const profile = page.getByRole('button', { name: 'wave1-secondary', exact: true })
      await profile.click()
      await expect(profile).toHaveAttribute('aria-pressed', 'true', { timeout: 30000 })
      await page.getByText('Scheduled jobs', { exact: true }).click()
      await expect(page.getByText('No scheduled jobs yet', { exact: true }).first()).toBeVisible({ timeout: 30000 })
      fs.writeFileSync(path.join(output, 'profile-cron.json'), JSON.stringify({ profiles: profiles.profiles.map(profile => profile.name), selected: 'wave1-secondary', cronEmpty: true }))
      await captureEvidence(page, 'profile-cron')
    }
  } else {
    await page.waitForFunction(text => document.querySelector('#root')?.textContent?.includes(text), errorText, { timeout: 45000 })
  }
  const text = await page.locator('#root').innerText()
  assert(!text.includes('No QueryClient set') && !text.includes('Something broke in the interface'))
  assert(JSON.parse(fs.readFileSync(receipt, 'utf8')).protocolCalls > 0)
  await captureEvidence(page, remoteUrl ? 'packaged-connected' : 'packaged-failure')
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ passed: true, scenario: remoteUrl ? 'connected' : 'failure', errorText, pid: child.pid }))
  await send('Runtime.evaluate', { expression: "process.getBuiltinModule('module').createRequire(process.execPath)('electron').app.quit()" })
  console.log('Packaged guarded journey PASS:', output)
} finally {
  socket?.close()
  await browser?.close().catch(() => {})
  if (child.exitCode === null) {
    await deadline(new Promise(resolve => child.once('exit', resolve)), 5000, 'owned Electron exit').catch(() => child.kill())
  }
}
