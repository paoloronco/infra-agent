import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertCircle,
  Calendar,
  CheckCircle2,
  Download,
  FileText,
  Filter,
  RefreshCw,
  Search,
  Shield,
  Terminal,
  Trash2,
  XCircle
} from 'lucide-react'
import toast from 'react-hot-toast'
import { clearLogs, exportLogs, getLogs, getLogStats } from '../api'

const LEVEL_STYLES = {
  INFO: {
    badge: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
    border: 'border-l-sky-500',
    icon: Activity,
  },
  WARNING: {
    badge: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    border: 'border-l-amber-500',
    icon: AlertCircle,
  },
  ERROR: {
    badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
    border: 'border-l-red-500',
    icon: XCircle,
  },
}

const CATEGORY_ICONS = {
  ssh: Terminal,
  chat: FileText,
  auth: Shield,
  model: Activity,
  system: Activity,
  logging: Filter,
}

function StatCard({ icon: Icon, label, value, tone }) {
  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${tone}`}>
          <Icon size={18} className="text-white" />
        </div>
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
    </div>
  )
}

function DetailRow({ label, value, mono = false }) {
  if (value === undefined || value === null || value === '') return null
  return (
    <div className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-[120px_1fr] sm:gap-3">
      <span className="text-gray-500 dark:text-gray-400">{label}</span>
      <span className={`text-gray-800 dark:text-gray-200 break-all ${mono ? 'font-mono text-xs' : ''}`}>
        {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
      </span>
    </div>
  )
}

function LogRow({ item }) {
  const [open, setOpen] = useState(false)
  const levelStyle = LEVEL_STYLES[item.level] || LEVEL_STYLES.INFO
  const LevelIcon = levelStyle.icon
  const CategoryIcon = CATEGORY_ICONS[item.category] || FileText
  const details = item.details && typeof item.details === 'object' ? item.details : {}

  return (
    <div className={`border border-gray-200 dark:border-gray-700 border-l-4 ${levelStyle.border} rounded-xl p-4 bg-white dark:bg-gray-800`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold ${levelStyle.badge}`}>
              <LevelIcon size={12} />
              {item.level}
            </span>
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">
              <CategoryIcon size={12} />
              {item.category}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">{item.event_type}</span>
          </div>

          <h3 className="text-sm font-semibold text-gray-900 dark:text-white break-words">{item.message}</h3>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
            <span>{new Date(item.timestamp).toLocaleString()}</span>
            {item.host && <span>Host: {item.host}</span>}
            {item.username && <span>User: {item.username}</span>}
            {item.model && <span>Model: {item.model}</span>}
            {item.chat_id && <span>Chat: #{item.chat_id}</span>}
            {item.source && <span>Source: {item.source}</span>}
          </div>
        </div>

        <button
          onClick={() => setOpen(current => !current)}
          className="w-full shrink-0 text-sm px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 sm:w-auto"
        >
          {open ? 'Hide details' : 'Details'}
        </button>
      </div>

      {open && (
        <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 space-y-3">
          <DetailRow label="Details" value={details} mono />
          <DetailRow label="Command" value={details.command} mono />
          <DetailRow label="Exit code" value={details.exit_code} />
          <DetailRow label="Duration" value={details.duration_ms ? `${details.duration_ms} ms` : null} />
          <DetailRow label="Error" value={details.error || details.stderr} mono />
          <DetailRow label="Output" value={details.stdout} mono />
        </div>
      )}
    </div>
  )
}

export default function Logs() {
  const [logs, setLogs] = useState([])
  const [stats, setStats] = useState({ total: 0, info: 0, warning: 0, error: 0, categories: {} })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(25)
  const [totalPages, setTotalPages] = useState(0)
  const [totalItems, setTotalItems] = useState(0)
  const [filters, setFilters] = useState({
    level: '',
    category: '',
    search: '',
    start_time: '',
    end_time: '',
  })

  const requestParams = useMemo(() => ({
    page,
    page_size: pageSize,
    level: filters.level || undefined,
    category: filters.category || undefined,
    search: filters.search || undefined,
    start_time: filters.start_time || undefined,
    end_time: filters.end_time || undefined,
  }), [filters, page, pageSize])

  const loadLogs = useCallback(async (showSpinner = true) => {
    if (showSpinner) setLoading(true)
    else setRefreshing(true)

    try {
      const [logsResponse, statsResponse] = await Promise.all([
        getLogs(requestParams),
        getLogStats({
          start_time: requestParams.start_time,
          end_time: requestParams.end_time,
        }),
      ])

      setLogs(logsResponse.items || [])
      setTotalPages(logsResponse.total_pages || 0)
      setTotalItems(logsResponse.total || 0)
      setStats(statsResponse || { total: 0, info: 0, warning: 0, error: 0, categories: {} })
    } catch (error) {
      toast.error(`Failed to load logs: ${error.message || 'Unknown error'}`)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [requestParams])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  const handleFilterChange = key => event => {
    const value = event.target.value
    setPage(1)
    setFilters(current => ({ ...current, [key]: value }))
  }

  const handleClearLogs = async () => {
    if (!window.confirm('Clear all application logs?')) return

    try {
      await clearLogs()
      toast.success('Logs cleared')
      setPage(1)
      loadLogs()
    } catch (error) {
      toast.error(`Failed to clear logs: ${error.message || 'Unknown error'}`)
    }
  }

  const handleExportLogs = async () => {
    try {
      const blob = await exportLogs({
        level: requestParams.level,
        start_time: requestParams.start_time,
        end_time: requestParams.end_time,
      })
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `app-logs-${new Date().toISOString().slice(0, 10)}.txt`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.URL.revokeObjectURL(url)
      toast.success('Logs exported')
    } catch (error) {
      toast.error(`Failed to export logs: ${error.message || 'Unknown error'}`)
    }
  }

  const categoryOptions = useMemo(() => {
    return Object.keys(stats.categories || {}).sort()
  }, [stats.categories])

  return (
    <div className="mx-auto max-w-7xl p-4 sm:p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">Logs</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Application events for chat, SSH, auth and model activity</p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <button
            onClick={() => loadLogs(false)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={handleExportLogs}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500"
          >
            <Download size={16} />
            Export
          </button>
          <button
            onClick={handleClearLogs}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-red-600/90 text-white hover:bg-red-600"
          >
            <Trash2 size={16} />
            Clear
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <StatCard icon={Activity} label="Total Events" value={stats.total} tone="bg-indigo-500" />
        <StatCard icon={CheckCircle2} label="Info" value={stats.info} tone="bg-sky-500" />
        <StatCard icon={AlertCircle} label="Warnings" value={stats.warning} tone="bg-amber-500" />
        <StatCard icon={XCircle} label="Errors" value={stats.error} tone="bg-red-500" />
      </div>

      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div className="md:col-span-2">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Search</label>
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                value={filters.search}
                onChange={handleFilterChange('search')}
                placeholder="Search message, event, host, model..."
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Level</label>
            <select
              value={filters.level}
              onChange={handleFilterChange('level')}
              className="w-full py-2 px-3 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All levels</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>

          <div>
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Category</label>
            <select
              value={filters.category}
              onChange={handleFilterChange('category')}
              className="w-full py-2 px-3 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All categories</option>
              {categoryOptions.map(category => (
                <option key={category} value={category}>{category}</option>
              ))}
            </select>
          </div>

          <div className="flex items-end">
            <button
              onClick={() => {
                setPage(1)
                setFilters({ level: '', category: '', search: '', start_time: '', end_time: '' })
              }}
              className="w-full py-2 px-3 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              Reset filters
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
          <div>
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">Start time</label>
            <div className="relative">
              <Calendar size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="datetime-local"
                value={filters.start_time}
                onChange={handleFilterChange('start_time')}
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1 block">End time</label>
            <div className="relative">
              <Calendar size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="datetime-local"
                value={filters.end_time}
                onChange={handleFilterChange('end_time')}
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Showing {logs.length} of {totalItems} log entries
        </p>
        {loading && (
          <div className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <RefreshCw size={16} className="animate-spin" />
            Loading logs...
          </div>
        )}
      </div>

      <div className="space-y-3">
        {!loading && logs.length === 0 ? (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-12 text-center">
            <FileText size={36} className="mx-auto mb-4 text-gray-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">No logs found</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">Try adjusting your filters or generate some activity from chat, SSH, auth or models.</p>
          </div>
        ) : (
          logs.map(item => <LogRow key={item.id} item={item} />)
        )}
      </div>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-sm text-gray-500 dark:text-gray-400">
          Page {totalPages === 0 ? 0 : page} of {totalPages}
        </span>
        <div className="flex w-full gap-2 sm:w-auto">
          <button
            onClick={() => setPage(current => Math.max(1, current - 1))}
            disabled={page <= 1}
            className="flex-1 px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed sm:flex-none"
          >
            Previous
          </button>
          <button
            onClick={() => setPage(current => (totalPages > 0 ? Math.min(totalPages, current + 1) : current))}
            disabled={totalPages === 0 || page >= totalPages}
            className="flex-1 px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed sm:flex-none"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}