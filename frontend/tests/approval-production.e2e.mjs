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

function sse(payload) {
  return `data: ${JSON.stringify(payload)}\n\n`
}

async function mockCommonRoutes(page, state) {
  await page.route('**/api/auth/config', route => route.fulfill({ json: { enabled: false } }))
  await page.route('**/api/models/providers', route => route.fulfill({ json: [{ id: 'openai', enabled: true, api_key_set: true }] }))
  await page.route('**/systems', route => route.fulfill({ json: [{ id: 'host1', name: 'web-prod' }] }))
  await page.route('**/api/chats', route => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: [state.chatListItem()] })
    }
    return route.fallback()
  })
  await page.route('**/api/chats/1', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: state.chat() })
    if (route.request().method() === 'PATCH') return route.fulfill({ json: state.chatListItem() })
    return route.fallback()
  })
}

async function assertApprovalControls(page, command) {
  const card = page.getByTestId('approval-card').last()
  await card.waitFor({ state: 'visible', timeout: 15_000 })
  await card.getByText(command).waitFor({ state: 'visible', timeout: 10_000 })
  assert(await card.getByRole('button', { name: 'APPROVE' }).isVisible(), 'APPROVE button is not visible')
  assert(await card.getByRole('button', { name: 'DENY' }).isVisible(), 'DENY button is not visible')
  assert(await card.getByRole('button', { name: 'OTHER' }).isVisible(), 'OTHER button is not visible')
  assert(await page.locator('textarea[placeholder="Approval pending..."]').isDisabled(), 'Chat input is not blocked during approval')
  await card.getByRole('button', { name: 'OTHER' }).click()
  assert(await page.locator('textarea[placeholder="Alternative instructions..."]').first().isVisible(), 'OTHER textarea did not open')
}

async function runRecoveredApprovalScenario(browser, baseUrl) {
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  const command = 'systemctl restart nginx\n/usr/bin/journalctl -u nginx -n 20'
  let approved = false
  let approveCalls = 0

  const pendingApproval = {
    id: 'approval-recovered',
    chat_id: 1,
    assistant_message_id: 10,
    run_id: 'run-recovered',
    action_type: 'ssh_command',
    system_name: 'web-prod',
    command,
    risk_level: 'high',
    reason: 'Restarting a critical service can interrupt active traffic.',
    status: 'waiting_approval',
  }

  const chatBase = {
    id: 1,
    title: 'Approval recovery test',
    model: 'gpt-5.5',
    target_host_id: 'host1',
    target_host: 'web-prod',
    target_host_missing: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 1,
    active_run: null,
  }

  const completedMessage = {
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
      'Continuing autonomous troubleshooting with this result...',
      '',
      'The service is healthy after restart.',
    ].join('\n'),
    status: 'complete',
    attachments: [],
    approval: { ...pendingApproval, status: 'approved' },
  }

  const state = {
    chatListItem: () => ({ ...chatBase, pending_approval: approved ? null : pendingApproval }),
    chat: () => ({
      ...chatBase,
      messages: approved
        ? [completedMessage]
        : [{
            id: 10,
            chat_id: 1,
            role: 'assistant',
            content: 'The agent wants to execute this command. It will not run until you approve it.',
            status: 'approval_required',
            attachments: [],
            approval: null,
          }],
      pending_approval: approved ? null : pendingApproval,
      active_run: approved ? null : { id: 'run-recovered', status: 'waiting_approval' },
    }),
  }

  await mockCommonRoutes(page, state)
  await page.route('**/api/chats/1/approvals/approval-recovered', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = JSON.parse(route.request().postData() || '{}')
    assert(body.decision === 'approve', 'APPROVE must send decision=approve')
    approveCalls += 1
    approved = true
    return route.fulfill({ json: state.chat() })
  })

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await assertApprovalControls(page, command)
  await page.getByTestId('approval-card').last().getByRole('button', { name: 'APPROVE' }).click()
  await page.getByText('approved-output').waitFor({ state: 'visible', timeout: 10_000 })
  await page.getByText('Continuing autonomous troubleshooting').waitFor({ state: 'visible', timeout: 10_000 })
  assert(approveCalls === 1, `Expected one approve call, got ${approveCalls}`)
  assert(!(await page.getByTestId('approval-card').last().isVisible().catch(() => false)), 'Approval card should disappear after approve')
  await page.close()
}

async function runStreamingApprovalScenario(browser, baseUrl) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  const command = 'systemctl restart nginx'
  let phase = 'empty'
  let approveCalls = 0
  let commandExecuted = false
  let continuationObserved = false

  const pendingApproval = {
    id: 'approval-stream',
    chat_id: 1,
    assistant_message_id: 22,
    run_id: 'run-stream',
    action_type: 'ssh_command',
    system_name: 'web-prod',
    command,
    risk_level: 'high',
    reason: 'Restarting nginx can interrupt active traffic.',
    status: 'approval_required',
  }

  const chatBase = {
    id: 1,
    title: 'Risky command stream',
    model: 'gpt-5.5',
    target_host_id: 'host1',
    target_host: 'web-prod',
    target_host_missing: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 0,
  }

  const messagesForPhase = () => {
    if (phase === 'empty') return []
    if (phase === 'approval') {
      return [
        { id: 21, chat_id: 1, role: 'user', content: `Please run ${command}`, status: 'complete', attachments: [] },
        {
          id: 22,
          chat_id: 1,
          role: 'assistant',
          content: 'The agent wants to execute this command. It will not run until you approve it.',
          status: 'approval_required',
          attachments: [],
          approval: pendingApproval,
        },
      ]
    }
    return [
      { id: 21, chat_id: 1, role: 'user', content: `Please run ${command}`, status: 'complete', attachments: [] },
      {
        id: 22,
        chat_id: 1,
        role: 'assistant',
        content: [
          'Approved command completed.',
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
          'nginx restarted',
          '```',
          '',
          'Continuing autonomous troubleshooting with this result...',
          '',
          'Continuation complete: nginx is running.',
        ].join('\n'),
        status: 'complete',
        attachments: [],
        approval: { ...pendingApproval, status: 'approved' },
      },
    ]
  }

  const state = {
    chatListItem: () => ({
      ...chatBase,
      message_count: messagesForPhase().length,
      pending_approval: phase === 'approval' ? pendingApproval : null,
    }),
    chat: () => ({
      ...chatBase,
      messages: messagesForPhase(),
      pending_approval: phase === 'approval' ? pendingApproval : null,
      active_run: phase === 'complete' ? null : phase === 'approval' ? { id: 'run-stream', status: 'waiting_approval' } : null,
    }),
  }

  await mockCommonRoutes(page, state)
  await page.route('**/api/chats/1/messages', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = JSON.parse(route.request().postData() || '{}')
    assert(body.content.includes(command), 'Risky command prompt was not sent')
    phase = 'approval'
    return route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: sse({
        approvalRequired: pendingApproval,
        content: 'Approval required before running this action.',
        message_id: 22,
        run_id: 'run-stream',
      }),
    })
  })
  await page.route('**/api/chats/1/approvals/approval-stream', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = JSON.parse(route.request().postData() || '{}')
    assert(body.decision === 'approve', 'Streaming APPROVE must send decision=approve')
    approveCalls += 1
    commandExecuted = true
    continuationObserved = true
    phase = 'complete'
    return route.fulfill({ json: state.chat() })
  })

  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => document.body.innerText.includes('GPT-5.5'))
  const composer = page.locator('textarea').last()
  await composer.fill(`Please run ${command}`)
  await composer.press('Enter')
  await assertApprovalControls(page, command)
  await page.getByTestId('approval-card').last().getByRole('button', { name: 'APPROVE' }).click()
  await page.getByText('nginx restarted').waitFor({ state: 'visible', timeout: 10_000 })
  await page.getByText('Continuation complete: nginx is running.').waitFor({ state: 'visible', timeout: 10_000 })
  assert(approveCalls === 1, `Expected one streaming approve call, got ${approveCalls}`)
  assert(commandExecuted, 'Approved command was not executed by the mocked runtime')
  assert(continuationObserved, 'Task did not continue after command execution')
  await page.close()
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
    try {
      await runRecoveredApprovalScenario(browser, baseUrl)
      await runStreamingApprovalScenario(browser, baseUrl)
    } finally {
      await browser.close()
    }
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
