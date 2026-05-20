import React, { useState, useEffect } from 'react'
import { Plus, Play, Trash2, ToggleLeft, ToggleRight, Clock } from 'lucide-react'
import { getCronJobs, createCronJob, updateCronJob, deleteCronJob, runCronJob } from '../api'
import toast from 'react-hot-toast'

const MODELS = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768']
const SCHEDULES = [
  { label: 'Every hour',    value: '0 * * * *' },
  { label: 'Daily 9am',     value: '0 9 * * *' },
  { label: 'Daily midnight',value: '0 0 * * *' },
  { label: 'Every Monday',  value: '0 9 * * 1' },
  { label: 'Custom',        value: 'custom' },
]

function JobForm({ onSave, onCancel }) {
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState(MODELS[0])
  const [schedule, setSchedule] = useState(SCHEDULES[1].value)
  const [customSchedule, setCustomSchedule] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    const finalSchedule = schedule === 'custom' ? customSchedule : schedule
    await onSave({ name, prompt, model, schedule: finalSchedule })
  }

  return (
    <form onSubmit={handleSubmit}
      className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 mb-4">
      <h3 className="font-semibold text-gray-900 dark:text-white mb-4">New Cron Job</h3>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">Name</label>
          <input value={name} onChange={e => setName(e.target.value)} required
            className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
              bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500" />
        </div>
        <div>
          <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">Model</label>
          <select value={model} onChange={e => setModel(e.target.value)}
            className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
              bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500">
            {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      </div>
      <div className="mb-3">
        <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">Prompt</label>
        <textarea value={prompt} onChange={e => setPrompt(e.target.value)} required rows={3}
          className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
            bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500 resize-none" />
      </div>
      <div className="mb-4">
        <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">Schedule</label>
        <select value={schedule} onChange={e => setSchedule(e.target.value)}
          className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
            bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500">
          {SCHEDULES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        {schedule === 'custom' && (
          <input value={customSchedule} onChange={e => setCustomSchedule(e.target.value)}
            placeholder="cron expression, e.g. 0 9 * * 1-5"
            className="mt-2 w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700
              bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-indigo-500" />
        )}
      </div>
      <div className="flex gap-2">
        <button type="submit"
          className="flex-1 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium">
          Create Job
        </button>
        <button type="button" onClick={onCancel}
          className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700
            text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700">
          Cancel
        </button>
      </div>
    </form>
  )
}

export default function CronJobs() {
  const [jobs, setJobs] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [running, setRunning] = useState(null)

  const load = () => getCronJobs().then(setJobs).catch(() => {})
  useEffect(() => { load() }, [])

  const handleCreate = async (data) => {
    await createCronJob(data)
    toast.success('Job created')
    setShowForm(false)
    load()
  }

  const handleToggle = async (job) => {
    await updateCronJob(job.id, { enabled: !job.enabled })
    load()
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this job?')) return
    await deleteCronJob(id)
    toast.success('Job deleted')
    load()
  }

  const handleRun = async (id) => {
    setRunning(id)
    try {
      const res = await runCronJob(id)
      if (res.success) toast.success('Job completed')
      else toast.error(res.error || 'Job failed')
      load()
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Cron Jobs</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">Scheduled AI tasks</p>
        </div>
        <button onClick={() => setShowForm(s => !s)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500
            text-white text-sm font-medium transition-colors">
          <Plus size={16} /> New Job
        </button>
      </div>

      {showForm && <JobForm onSave={handleCreate} onCancel={() => setShowForm(false)} />}

      {jobs.length === 0 && !showForm ? (
        <div className="text-center py-16 text-gray-400">
          <Clock size={40} className="mx-auto mb-3 opacity-30" />
          <p>No cron jobs yet. Create one to automate AI tasks.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map(job => (
            <div key={job.id}
              className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-medium text-gray-900 dark:text-white">{job.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${job.enabled
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-500'}`}>
                      {job.enabled ? 'Active' : 'Disabled'}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate mb-1">{job.prompt}</p>
                  <div className="flex items-center gap-3 text-xs text-gray-400">
                    <span>⏰ {job.schedule}</span>
                    <span>🤖 {job.model}</span>
                    {job.last_run && <span>Last: {new Date(job.last_run).toLocaleString()}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button onClick={() => handleRun(job.id)} disabled={running === job.id}
                    className="p-2 rounded-lg text-gray-400 hover:text-indigo-500 hover:bg-indigo-50
                      dark:hover:bg-indigo-900/20 transition-colors disabled:opacity-50">
                    <Play size={16} />
                  </button>
                  <button onClick={() => handleToggle(job)}
                    className="p-2 rounded-lg text-gray-400 hover:text-green-500 transition-colors">
                    {job.enabled ? <ToggleRight size={20} className="text-green-500" /> : <ToggleLeft size={20} />}
                  </button>
                  <button onClick={() => handleDelete(job.id)}
                    className="p-2 rounded-lg text-gray-400 hover:text-red-500 transition-colors">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
