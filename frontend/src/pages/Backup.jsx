import React, { useState, useRef } from 'react'
import {
  Download, Upload, Shield, Database, Key, Terminal,
  MessageSquare, BarChart2, Clock, Brain, Users,
  CheckCircle2, AlertTriangle, Loader2, Lock, Unlock, Eye, EyeOff,
  FileArchive, Info, RefreshCw,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { exportBackup, previewBackup, importBackup } from '../api'

// ── Section definitions ────────────────────────────────────────────────────────
const SECTIONS = [
  {
    id: 'users',
    label: 'Users & Auth',
    icon: Users,
    desc: 'User accounts, passwords (hashed), roles, auth settings',
    sensitive: false,
  },
  {
    id: 'model_configs',
    label: 'AI Models & API Keys',
    icon: Brain,
    desc: 'Provider configurations and API keys (obfuscated in backup)',
    sensitive: true,
  },
  {
    id: 'systems',
    label: 'SSH Systems',
    icon: Terminal,
    desc: 'Registered hosts, hierarchy, connection configs',
    sensitive: false,
  },
  {
    id: 'ssh_keys',
    label: 'SSH Key Files',
    icon: Key,
    desc: 'Private and public key files stored on disk',
    sensitive: true,
  },
  {
    id: 'chats',
    label: 'Chat History',
    icon: MessageSquare,
    desc: 'All conversations, messages, and file attachments metadata',
    sensitive: false,
  },
  {
    id: 'cron_jobs',
    label: 'Cron Jobs',
    icon: Clock,
    desc: 'Scheduled automation tasks',
    sensitive: false,
  },
  {
    id: 'agent_memory',
    label: 'Agent Memory',
    icon: Database,
    desc: 'Cross-session agent memory and context',
    sensitive: false,
  },
  {
    id: 'usage_logs',
    label: 'Usage Statistics',
    icon: BarChart2,
    desc: 'Token usage and cost tracking data',
    sensitive: false,
  },
]

// ── Password field ────────────────────────────────────────────────────────────
function PasswordField({ value, onChange, placeholder, label }) {
  const [show, setShow] = useState(false)
  return (
    <div>
      {label && <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">{label}</label>}
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full pr-9 pl-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
            bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
            placeholder-gray-400 outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <button type="button" onClick={() => setShow(s => !s)}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          {show ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
    </div>
  )
}

// ── Record count badge ────────────────────────────────────────────────────────
function CountBadge({ n }) {
  if (n == null) return null
  return (
    <span className="ml-auto text-[11px] font-mono tabular-nums px-1.5 py-0.5 rounded-full
      bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400 ring-1 ring-inset ring-indigo-200 dark:ring-indigo-800">
      {n.toLocaleString()}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Backup() {
  // Export state
  const [exportIncludes, setExportIncludes] = useState(
    new Set(SECTIONS.map(s => s.id))
  )
  const [exportPassword, setExportPassword] = useState('')
  const [exporting, setExporting] = useState(false)

  // Import state
  const [importFile, setImportFile] = useState(null)
  const [importPassword, setImportPassword] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef(null)

  // ── Export ──────────────────────────────────────────────────────────────────
  const toggleSection = id => {
    setExportIncludes(prev => {
      const s = new Set(prev)
      s.has(id) ? s.delete(id) : s.add(id)
      return s
    })
  }

  const handleExport = async () => {
    if (exportIncludes.size === 0) { toast.error('Select at least one section'); return }
    if (hasSensitive && !exportPassword) {
      toast.error('Set an encryption password when exporting API keys or SSH key files')
      return
    }
    setExporting(true)
    try {
      const filename = await exportBackup([...exportIncludes], exportPassword || null)
      toast.success(`Backup saved: ${filename}`)
    } catch (e) {
      toast.error(`Export failed: ${e.message}`)
    } finally {
      setExporting(false)
    }
  }

  // ── Import ──────────────────────────────────────────────────────────────────
  const handleFileSelect = async (file) => {
    if (!file) return
    setImportFile(file)
    setPreview(null)
    setImportResult(null)
    setShowConfirm(false)
    setPreviewLoading(true)
    try {
      const info = await previewBackup(file, importPassword || null)
      setPreview(info)
    } catch (e) {
      if (e.message?.includes('password') || e.message?.includes('encrypted')) {
        setPreview({ needsPassword: true })
      } else {
        toast.error(`Cannot read backup: ${e.message}`)
        setImportFile(null)
      }
    } finally {
      setPreviewLoading(false)
    }
  }

  const handlePasswordAndPreview = async () => {
    if (!importFile || !importPassword) return
    setPreviewLoading(true)
    try {
      const info = await previewBackup(importFile, importPassword)
      setPreview(info)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleImport = async () => {
    if (!importFile) return
    setImporting(true)
    setShowConfirm(false)
    try {
      const result = await importBackup(importFile, importPassword || null)
      setImportResult(result)
      toast.success('Backup imported successfully')
    } catch (e) {
      toast.error(`Import failed: ${e.message}`)
    } finally {
      setImporting(false)
    }
  }

  const hasSensitive = SECTIONS.some(s => s.sensitive && exportIncludes.has(s.id))

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <FileArchive size={24} className="text-indigo-500" />
          Backup & Restore
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Export a complete snapshot of your instance for migration or disaster recovery.
        </p>
      </div>

      {/* ── EXPORT ─────────────────────────────────────────────────────────── */}
      <section className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm">
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-50 dark:bg-indigo-950/60">
            <Download size={18} className="text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <h2 className="font-semibold text-gray-900 dark:text-white">Export Backup</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">Choose what to include and download a single .aib file</p>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Section selection */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Include in backup</span>
              <div className="flex gap-2">
                <button onClick={() => setExportIncludes(new Set(SECTIONS.map(s => s.id)))}
                  className="text-xs text-indigo-500 hover:underline">All</button>
                <span className="text-gray-300 dark:text-gray-600">·</span>
                <button onClick={() => setExportIncludes(new Set())}
                  className="text-xs text-gray-400 hover:underline">None</button>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {SECTIONS.map(section => {
                const Icon = section.icon
                const checked = exportIncludes.has(section.id)
                return (
                  <label key={section.id}
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors
                      ${checked
                        ? 'border-indigo-300 dark:border-indigo-700 bg-indigo-50/50 dark:bg-indigo-950/30'
                        : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                      }`}>
                    <input type="checkbox" checked={checked}
                      onChange={() => toggleSection(section.id)}
                      className="mt-0.5 accent-indigo-600" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <Icon size={13} className={checked ? 'text-indigo-500' : 'text-gray-400'} />
                        <span className="text-sm font-medium text-gray-800 dark:text-gray-200">{section.label}</span>
                        {section.sensitive && (
                          <span className="text-[10px] px-1 py-px rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 ring-1 ring-amber-200 dark:ring-amber-800">
                            sensitive
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 leading-tight">{section.desc}</p>
                    </div>
                  </label>
                )
              })}
            </div>
          </div>

          {/* Optional encryption */}
          <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-700/40 border border-gray-200 dark:border-gray-700 space-y-3">
            <div className="flex items-center gap-2">
              {exportPassword ? <Lock size={14} className="text-indigo-500" /> : <Unlock size={14} className="text-gray-400" />}
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                {exportPassword ? 'Encrypted backup' : hasSensitive ? 'Encryption required' : 'Optional encryption'}
              </span>
            </div>
            <PasswordField
              value={exportPassword}
              onChange={setExportPassword}
              placeholder="Leave blank for unencrypted backup"
              label={null}
            />
            <p className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
              {exportPassword
                ? 'Backup will be encrypted with AES-256 (Fernet). You will need this password to restore.'
                : hasSensitive
                  ? 'Sensitive exports include API keys or SSH keys and must be encrypted.'
                  : 'Without a password, the file is a standard ZIP for easy migration.'}
            </p>
          </div>

          {/* Sensitive data warning */}
          {hasSensitive && (
            <div className="flex gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
              <AlertTriangle size={15} className="text-amber-600 dark:text-amber-400 shrink-0 mt-px" />
              <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
                Your backup includes <strong>SSH keys and/or API keys</strong>. Encryption is required and the file should still be treated like a password file.
              </p>
            </div>
          )}

          <button
            onClick={handleExport}
            disabled={exporting || exportIncludes.size === 0 || (hasSensitive && !exportPassword)}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl
              bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed
              text-white font-medium text-sm transition-colors shadow-sm"
          >
            {exporting
              ? <><Loader2 size={16} className="animate-spin" /> Generating backup…</>
              : <><Download size={16} /> Export Backup</>
            }
          </button>
        </div>
      </section>

      {/* ── IMPORT ─────────────────────────────────────────────────────────── */}
      <section className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm">
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700 flex items-center gap-3">
          <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-950/60">
            <Upload size={18} className="text-rose-600 dark:text-rose-400" />
          </div>
          <div>
            <h2 className="font-semibold text-gray-900 dark:text-white">Import Backup</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">Restore from a .aib file — this will replace existing data</p>
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          {/* Drop zone */}
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => {
              e.preventDefault(); setDragging(false)
              const f = e.dataTransfer.files[0]
              if (f) handleFileSelect(f)
            }}
            className={`relative flex flex-col items-center justify-center gap-2 py-8 rounded-xl border-2 border-dashed cursor-pointer transition-colors
              ${dragging
                ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-950/30'
                : importFile
                  ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/20'
                  : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-600 bg-gray-50 dark:bg-gray-700/30'
              }`}
          >
            <input ref={fileInputRef} type="file" accept=".aib,.zip"
              className="hidden" onChange={e => handleFileSelect(e.target.files[0])} />
            {importFile ? (
              <>
                <FileArchive size={28} className="text-emerald-500" />
                <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">{importFile.name}</p>
                <p className="text-xs text-gray-400">{(importFile.size / 1024).toFixed(1)} KB · click to change</p>
              </>
            ) : (
              <>
                <Upload size={28} className="text-gray-400" />
                <p className="text-sm text-gray-600 dark:text-gray-300">Drop .aib file here or <span className="text-indigo-500 font-medium">browse</span></p>
                <p className="text-xs text-gray-400">Supports plain and encrypted AIB backups</p>
              </>
            )}
          </div>

          {/* Password for encrypted backup */}
          {(preview?.needsPassword || (preview?.encrypted && !preview?.needsPassword)) && (
            <div className="space-y-2">
              <PasswordField
                value={importPassword}
                onChange={setImportPassword}
                placeholder="Backup decryption password"
                label="Backup password"
              />
              {preview?.needsPassword && (
                <button onClick={handlePasswordAndPreview} disabled={!importPassword || previewLoading}
                  className="flex items-center gap-1.5 text-sm text-indigo-500 hover:text-indigo-600 disabled:opacity-40">
                  {previewLoading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  Verify password & preview
                </button>
              )}
            </div>
          )}

          {/* Preview card */}
          {previewLoading && !preview && (
            <div className="flex items-center gap-2 py-3 text-sm text-gray-400">
              <Loader2 size={15} className="animate-spin" /> Reading backup…
            </div>
          )}

          {preview && !preview.needsPassword && (
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-4 py-3 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
                {preview.compatible
                  ? <CheckCircle2 size={15} className="text-emerald-500" />
                  : <AlertTriangle size={15} className="text-amber-500" />
                }
                <span className="text-sm font-medium text-gray-700 dark:text-gray-200">Backup details</span>
                {preview.encrypted && (
                  <span className="ml-auto flex items-center gap-1 text-xs text-indigo-500">
                    <Lock size={11} /> Encrypted
                  </span>
                )}
              </div>
              <div className="px-4 py-3 space-y-3">
                <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                  <div className="text-gray-400">Created</div>
                  <div className="text-gray-700 dark:text-gray-200 font-mono">
                    {preview.created_at ? new Date(preview.created_at).toLocaleString() : '—'}
                  </div>
                  <div className="text-gray-400">Source host</div>
                  <div className="text-gray-700 dark:text-gray-200 font-mono">{preview.hostname || '—'}</div>
                  <div className="text-gray-400">Format version</div>
                  <div className="text-gray-700 dark:text-gray-200 font-mono">{preview.format_version || '—'}</div>
                  <div className="text-gray-400">Compatible</div>
                  <div className={preview.compatible ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}>
                    {preview.compatible ? 'Yes' : 'Version mismatch — restore may fail'}
                  </div>
                </div>

                {/* Contents */}
                <div className="pt-1">
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">Contents</p>
                  <div className="flex flex-wrap gap-1.5">
                    {(preview.includes || []).map(inc => {
                      const sec = SECTIONS.find(s => s.id === inc)
                      const Icon = sec?.icon || Database
                      const count = preview.record_counts?.[inc]
                      return (
                        <span key={inc}
                          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg
                            bg-indigo-50 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300
                            border border-indigo-200 dark:border-indigo-800">
                          <Icon size={10} />
                          {sec?.label || inc}
                          {count != null && <CountBadge n={count} />}
                        </span>
                      )
                    })}
                  </div>
                </div>

                {preview.api_keys_obfuscated && (
                  <div className="flex gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                    <Info size={13} className="text-amber-600 shrink-0 mt-px" />
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                      API keys in this backup are obfuscated. They will be automatically restored if the format is compatible.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Import result */}
          {importResult && (
            <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 px-4 py-4 space-y-2">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={16} className="text-emerald-600 dark:text-emerald-400" />
                <span className="text-sm font-semibold text-emerald-700 dark:text-emerald-300">Import complete</span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-emerald-700 dark:text-emerald-400">
                {Object.entries(importResult.summary).map(([k, v]) => (
                  <span key={k}><span className="font-medium">{v}</span> {k.replace(/_/g, ' ')}</span>
                ))}
              </div>
              <p className="text-xs text-emerald-600 dark:text-emerald-500">Reload the page to see restored data.</p>
            </div>
          )}

          {/* Destructive warning */}
          <div className="flex gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800">
            <AlertTriangle size={14} className="text-rose-600 dark:text-rose-400 shrink-0 mt-px" />
            <p className="text-xs text-rose-700 dark:text-rose-300 leading-relaxed">
              Importing a backup <strong>replaces all existing data</strong> in the selected sections.
              This cannot be undone. Export a current backup first if you want to preserve your data.
            </p>
          </div>

          {/* Confirm step */}
          {!showConfirm ? (
            <button
              onClick={() => preview && !preview.needsPassword && setShowConfirm(true)}
              disabled={!preview || preview.needsPassword || importing || !preview.compatible}
              className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl
                border-2 border-rose-300 dark:border-rose-700
                text-rose-700 dark:text-rose-400 font-medium text-sm
                hover:bg-rose-50 dark:hover:bg-rose-950/30
                disabled:opacity-40 disabled:cursor-not-allowed
                transition-colors"
            >
              <Upload size={16} /> Import Backup
            </button>
          ) : (
            <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/30 border-2 border-rose-300 dark:border-rose-700 space-y-3">
              <p className="text-sm font-semibold text-rose-700 dark:text-rose-300 text-center">
                Are you sure? This will overwrite existing data.
              </p>
              <div className="flex gap-2">
                <button onClick={() => setShowConfirm(false)}
                  className="flex-1 py-2 rounded-lg border border-gray-300 dark:border-gray-600
                    text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                  Cancel
                </button>
                <button onClick={handleImport} disabled={importing}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg
                    bg-rose-600 hover:bg-rose-500 text-white text-sm font-medium
                    disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                  {importing
                    ? <><Loader2 size={14} className="animate-spin" /> Restoring…</>
                    : <><Upload size={14} /> Yes, restore</>
                  }
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── INFO BOX ───────────────────────────────────────────────────────── */}
      <section className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 px-6 py-5 shadow-sm">
        <div className="flex items-start gap-3">
          <Shield size={18} className="text-indigo-500 shrink-0 mt-0.5" />
          <div className="space-y-1.5 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
            <p className="font-semibold text-gray-700 dark:text-gray-300">Security & compatibility notes</p>
            <ul className="list-disc pl-4 space-y-1">
              <li>API keys are obfuscated in the backup. They restore automatically on the same or a new instance.</li>
              <li>SSH private key files are included verbatim. Connections will work immediately after restore.</li>
              <li>Encrypted backups use AES-256 (Fernet / PBKDF2). The password is never stored.</li>
              <li>Backup files are self-contained — no internet connection required to restore.</li>
              <li>Restore a backup only on the same app version or a newer compatible release.</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  )
}
