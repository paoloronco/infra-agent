import { spawn } from 'node:child_process'
import net from 'node:net'
import { chromium } from 'playwright'

const HOST = '127.0.0.1'
const START_PORT = Number(process.env.E2E_PORT || 4173)

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function getFreePort(startPort) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      const server = net.createServer()
      server.once('error', (err) => {
        if (err.code === 'EADDRINUSE') return tryPort(port + 1)
        reject(err)
      })
      server.once('listening', () => {
        server.close(() => resolve(port))
      })
      server.listen(port, HOST)
    }
    tryPort(startPort)
  })
}

async function waitForPreview(url, proc) {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      throw new Error(`Preview exited early with code ${proc.exitCode}`)
    }
    try {
      const res = await fetch(url)
      if (res.ok) return
    } catch {
      // Server not ready yet.
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error(`Preview did not become ready at ${url}`)
}

async function run() {
  const port = await getFreePort(START_PORT)
  const baseUrl = `http://${HOST}:${port}`
  const preview = spawn(
    process.execPath,
    ['node_modules/vite/bin/vite.js', 'preview', '--host', HOST, '--port', String(port)],
    { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'pipe'] },
  )

  let stderr = ''
  preview.stderr.on('data', chunk => { stderr += chunk.toString() })

  try {
    await waitForPreview(baseUrl, preview)

    const browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })

    const command = 'systemctl restart nginx\n/usr/bin/journalctl -u nginx -n 20'
    let approved = false
    let approveCalls = 0

    const pendingApproval = {
      id: 'approval-e2e',
      chat_id: 1,
      assistant_message_id: 10,
      run_id: 'run-e2e',
      action_type: 'ssh_command',
      system_name: 'web-prod',
      command,
      risk_level: 'high',
      reason: 'Restarting a critical service can interrupt active traffic.',
      status: 'approval_required',
    }

    const chatBase = {
      id: 1,
      title: 'Approval production test',
      model: 'gpt-5.5',
      target_host_id: 'host1',
      target_host: 'web-prod',
      target_host_missing: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      message_count: 1,
      active_run: null,
    }

    const pendingChat = () => ({
      ...chatBase,
      messages: [{
        id: 10,
        chat_id: 1,
        role: 'assistant',
        content: 'The agent wants to execute this command. It will not run until you approve it.',
        status: 'approval_required',
        attachments: [],
        approval: null,
      }],
      pending_approval: pendingApproval,
    })

    const completedChat = () => ({
      ...chatBase,
      messages: [{
        id: 10,
        chat_id: 1,
        role: 'assistant',
        content: [
          'Approved command completed.',
          '',
          'Host: `web-prod`',
          '',
          'Command:',
          '```bash',
          command,
          '```',
          '',
          'Exit code: `0`',
          '',
          'STDOUT:',
          '```text',
          'approved-output',
          '```',
          '',
          'STDERR:',
          '```text',
          '[empty]',
          '```',
        ].join('\n'),
        status: 'complete',
        attachments: [],
        approval: { ...pendingApproval, status: 'approved' },
      }],
      pending_approval: null,
    })

    await page.route('**/api/auth/config', route => route.fulfill({ json: { enabled: false } }))
    await page.route('**/api/models/providers', route => route.fulfill({ json: [{ id: 'openai', enabled: true, api_key_set: true }] }))
    await page.route('**/systems', route => route.fulfill({ json: [{ id: 'host1', name: 'web-prod' }] }))
    await page.route('**/api/chats', route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: [{ ...chatBase, pending_approval: approved ? null : pendingApproval }] })
      }
      return route.fallback()
    })
    await page.route('**/api/chats/1', route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: approved ? completedChat() : pendingChat() })
      }
      return route.fulfill({ json: chatBase })
    })
    await page.route('**/api/chats/1/approvals/approval-e2e', route => {
      if (route.request().method() !== 'POST') return route.fallback()
      const body = JSON.parse(route.request().postData() || '{}')
      assert(body.decision === 'approve', 'APPROVE must send decision=approve')
      approveCalls += 1
      approved = true
      return route.fulfill({ json: completedChat() })
    })

    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await page.getByText('Risky action approval').waitFor({ state: 'visible', timeout: 15_000 })
    await page.getByText(command).waitFor({ state: 'visible', timeout: 10_000 })

    assert(await page.getByRole('button', { name: 'APPROVE' }).isVisible(), 'APPROVE button is not visible')
    assert(await page.getByRole('button', { name: 'DENY' }).isVisible(), 'DENY button is not visible')
    assert(await page.getByRole('button', { name: 'OTHER' }).isVisible(), 'OTHER button is not visible')
    assert(await page.locator('textarea[placeholder="Approval pending..."]').isDisabled(), 'Chat input is not blocked during approval')

    await page.getByRole('button', { name: 'OTHER' }).click()
    assert(await page.locator('textarea[placeholder="Alternative instructions..."]').isVisible(), 'OTHER textarea did not open')

    await page.getByRole('button', { name: 'APPROVE' }).click()
    await page.getByText('approved-output').waitFor({ state: 'visible', timeout: 10_000 })
    await page.getByText('Exit code:').waitFor({ state: 'visible', timeout: 10_000 })

    assert(approveCalls === 1, `Expected one approve call, got ${approveCalls}`)
    assert(!(await page.getByText('Risky action approval').isVisible().catch(() => false)), 'Approval card should disappear after approve')

    await browser.close()
    console.log('Approval production e2e passed')
  } finally {
    preview.kill()
    if (stderr.trim()) process.stderr.write(stderr)
  }
}

run().catch(err => {
  console.error(err)
  process.exit(1)
})
