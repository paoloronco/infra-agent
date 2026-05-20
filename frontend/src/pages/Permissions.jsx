import React, { useState } from 'react'
import { Shield, Plus, X, Save } from 'lucide-react'
import toast from 'react-hot-toast'

const OPERATOR_ALLOWED = [
  '/usr/bin/systemctl status *',
  '/usr/bin/systemctl show *',
  '/usr/bin/systemctl list-units *',
  '/usr/bin/systemctl start *',
  '/usr/bin/systemctl stop *',
  '/usr/bin/systemctl restart *',
  '/usr/bin/systemctl reload *',
  '/usr/bin/systemctl enable *',
  '/usr/bin/systemctl disable *',
  '/usr/bin/systemctl daemon-reload',
  '/usr/bin/journalctl',
  '/usr/bin/journalctl -u *',
  'journalctl',
  '/usr/bin/dmesg',
  'dmesg',
  '/usr/bin/uptime',
  '/usr/bin/free',
  '/usr/bin/df',
  '/usr/bin/du',
  '/usr/bin/top',
  '/usr/bin/ps',
  '/usr/bin/pgrep',
  '/usr/bin/pidstat',
  '/usr/bin/iostat',
  '/usr/bin/vmstat',
  '/usr/bin/lsblk',
  '/usr/bin/mount',
  '/usr/bin/findmnt',
  '/usr/bin/ping',
  '/usr/bin/traceroute',
  '/usr/bin/tracepath',
  '/usr/bin/dig',
  '/usr/bin/nslookup',
  '/usr/bin/host',
  '/usr/bin/curl',
  '/usr/bin/wget',
  'curl',
  'wget',
  '/usr/bin/ss',
  '/usr/sbin/ip',
  '/usr/sbin/ethtool',
  '/usr/bin/nmcli',
  '/usr/sbin/resolvectl',
  '/usr/bin/tail',
  '/usr/bin/head',
  '/usr/bin/grep',
  '/usr/bin/zgrep',
  '/usr/bin/awk',
  '/usr/bin/sed',
  '/usr/bin/less',
  '/usr/bin/cat',
  '/var/log/',
  '/var/log/nginx/',
  '/var/log/apache2/',
  '/var/log/mysql/',
  '/var/log/postgresql/',
  '/var/log/redis/',
  '/opt/*/logs/',
  '/srv/*/logs/',
]

const DEFAULT_BLOCKED = [
  'rm -rf',
  'dd if=/dev/zero',
  'mkfs',
  'fdisk',
  'parted',
  'gdisk',
  ':(){:|:&};:',
  'chmod 777 /',
  'shutdown',
  'reboot',
  'halt',
  'poweroff',
  'iptables -F',
  'ufw disable',
  'nft flush ruleset',
  'curl | sh',
  'wget | bash',
  'bash -i >& /dev/tcp',
]

const MODES = [
  {
    id: 'strict',
    label: 'Strict',
    desc: 'Read-only diagnostics only. No write operations.',
    color: 'text-green-500',
    allowed: [
      'systemctl status', 'journalctl', 'df -h', 'free -h',
      'top', 'ps aux', 'ip addr', 'ping', 'cat /etc/os-release',
      'uname -a', 'uptime', 'who', 'last', 'netstat',
    ],
    blocked: [
      'rm -rf', 'dd if=/dev/zero', 'mkfs', 'fdisk',
      ':(){:|:&};:', 'chmod 777 /', 'shutdown', 'reboot',
      'systemctl stop', 'systemctl restart', 'apt', 'yum', 'pip install',
    ],
  },
  {
    id: 'balanced',
    label: 'Balanced',
    desc: 'Diagnostics + safe service restarts. Confirm destructive actions.',
    color: 'text-amber-500',
    allowed: [
      'systemctl status', 'systemctl restart', 'systemctl start', 'systemctl stop',
      'journalctl', 'df -h', 'free -h', 'top', 'ps aux',
      'ip addr', 'ping', 'cat /etc/os-release', 'uname -a', 'uptime',
    ],
    blocked: DEFAULT_BLOCKED,
  },
  {
    id: 'operator',
    label: 'Operator',
    desc: 'Diagnostics, log access, networking, and service lifecycle operations.',
    color: 'text-indigo-500',
    allowed: OPERATOR_ALLOWED,
    blocked: DEFAULT_BLOCKED,
  },
  {
    id: 'full',
    label: 'Full Access',
    desc: 'All operations allowed. Use with caution.',
    color: 'text-red-500',
    allowed: ['*  (all commands allowed)'],
    blocked: [':(){:|:&};:'],  // only fork bomb blocked
  },
]

export default function Permissions() {
  const saved = (() => {
    try { return JSON.parse(localStorage.getItem('ai_permissions')) } catch { return null }
  })()

  const initialMode = saved?.mode || 'operator'
  const initialPreset = MODES.find(m => m.id === initialMode) || MODES.find(m => m.id === 'operator')
  const [mode, setMode] = useState(initialPreset.id)
  const [allowed, setAllowed] = useState(saved?.allowed || initialPreset.allowed)
  const [blocked, setBlocked] = useState(saved?.blocked || initialPreset.blocked)
  const [newAllowed, setNewAllowed] = useState('')
  const [newBlocked, setNewBlocked] = useState('')

  const handleModeChange = (newMode) => {
    setMode(newMode)
    const preset = MODES.find(m => m.id === newMode)
    setAllowed([...preset.allowed])
    setBlocked([...preset.blocked])
  }

  const save = () => {
    localStorage.setItem('ai_permissions', JSON.stringify({ mode, allowed, blocked }))
    toast.success('Local reference preset saved')
  }

  const addAllowed = () => {
    if (!newAllowed.trim()) return
    setAllowed(prev => [...prev, newAllowed.trim()])
    setNewAllowed('')
  }

  const addBlocked = () => {
    if (!newBlocked.trim()) return
    setBlocked(prev => [...prev, newBlocked.trim()])
    setNewBlocked('')
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">AI Safety Presets</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Local reference presets for this browser. Server-side guardrails enforce actual SSH tool safety.</p>
        </div>
        <button onClick={save}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500
            text-white text-sm font-medium transition-colors">
          <Save size={16} /> Save
        </button>
      </div>

      <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
        These presets document the intended remote operator scope. Actual enforcement happens on the backend and on each registered host through SSH, sudoers, and command validation.
      </div>

      {/* Mode selector */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
        {MODES.map(m => (
          <button key={m.id} onClick={() => handleModeChange(m.id)}
            className={`p-4 rounded-xl border-2 text-left transition-all
              ${mode === m.id
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600'}`}>
            <div className="flex items-center gap-2 mb-1">
              <Shield size={16} className={mode === m.id ? 'text-indigo-500' : 'text-gray-400'} />
              <span className={`font-semibold text-sm ${mode === m.id ? m.color : 'text-gray-700 dark:text-gray-300'}`}>
                {m.label}
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">{m.desc}</p>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Allowed */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <h2 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
            Allowed Commands
            <span className="ml-auto text-xs text-gray-400 font-normal">{allowed.length} rules</span>
          </h2>
          <div className="flex gap-2 mb-3">
            <input value={newAllowed} onChange={e => setNewAllowed(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addAllowed()}
              placeholder="Add command..."
              className="flex-1 text-xs px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100
                outline-none focus:ring-1 focus:ring-green-500" />
            <button onClick={addAllowed}
              className="p-2 rounded-lg bg-green-500 hover:bg-green-400 text-white transition-colors">
              <Plus size={14} />
            </button>
          </div>
          <div className="space-y-1.5 max-h-72 overflow-y-auto">
            {allowed.map((cmd, i) => (
              <div key={i} className="flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg
                bg-green-50 dark:bg-green-900/20">
                <code className="text-xs text-green-700 dark:text-green-400 flex-1 truncate">{cmd}</code>
                <button onClick={() => setAllowed(prev => prev.filter((_, j) => j !== i))}
                  className="text-green-400 hover:text-red-500 shrink-0 transition-colors">
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Blocked */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <h2 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
            Blocked Commands
            <span className="ml-auto text-xs text-gray-400 font-normal">{blocked.length} rules</span>
          </h2>
          <div className="flex gap-2 mb-3">
            <input value={newBlocked} onChange={e => setNewBlocked(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addBlocked()}
              placeholder="Add command..."
              className="flex-1 text-xs px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
                bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100
                outline-none focus:ring-1 focus:ring-red-500" />
            <button onClick={addBlocked}
              className="p-2 rounded-lg bg-red-500 hover:bg-red-400 text-white transition-colors">
              <Plus size={14} />
            </button>
          </div>
          <div className="space-y-1.5 max-h-72 overflow-y-auto">
            {blocked.map((cmd, i) => (
              <div key={i} className="flex items-center justify-between gap-2 px-3 py-1.5 rounded-lg
                bg-red-50 dark:bg-red-900/20">
                <code className="text-xs text-red-700 dark:text-red-400 flex-1 truncate">{cmd}</code>
                <button onClick={() => setBlocked(prev => prev.filter((_, j) => j !== i))}
                  className="text-red-400 hover:text-red-600 shrink-0 transition-colors">
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
