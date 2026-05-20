import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { CheckCircle, XCircle, Eye, EyeOff, Loader, ExternalLink } from 'lucide-react'
import { getProviders, updateProvider, testProvider } from '../api'
import { clearModelStatusCache } from '../components/ModelPicker'
import toast from 'react-hot-toast'

const PRIMARY_PROVIDER_IDS = ['openai', 'anthropic', 'gemini']
const OPENAI_AUTH_API_KEY = 'api_key'

function ProviderCard({ provider, onUpdate }) {
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  const isOllama = provider.id === 'ollama'
  const isOpenAI = provider.id === 'openai'
  const configured = isOllama ? provider.enabled : provider.api_key_set

  const handleSave = async () => {
    setSaving(true)
    try {
      await onUpdate(provider.id, {
        api_key: isOllama ? undefined : (apiKey || undefined),
        auth_mode: isOpenAI ? OPENAI_AUTH_API_KEY : undefined,
        enabled: true,
      })
      toast.success(`${provider.name} saved`)
      setApiKey('')
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Failed to save'
      toast.error(detail)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const res = await testProvider(provider.id)
      if (res.success) toast.success(`${provider.name}: ${res.message}`)
      else toast.error(`${provider.name}: ${res.message}`)
    } catch {
      toast.error('Test failed')
    } finally {
      setTesting(false)
    }
  }

  return (
    <article className="h-full min-h-[238px] rounded-xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-200/40 transition-colors dark:border-gray-700 dark:bg-gray-800 dark:shadow-none">
      <div className="flex h-full flex-col">
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-gray-950 dark:text-white">{provider.name}</h3>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              {isOllama ? 'Local provider' : 'API key authentication'}
            </p>
          </div>
          <a
            href={provider.docs_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950/40"
          >
            Docs
            <ExternalLink size={12} />
          </a>
        </div>

        <div className="mb-4">
          {configured ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-800">
              <CheckCircle size={13} />
              Configured
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-500 ring-1 ring-inset ring-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:ring-gray-700">
              <XCircle size={13} />
              Not configured
            </span>
          )}
        </div>

        <div className="flex-1">
          <label className="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">
            API Key {provider.api_key_preview && <span className="text-gray-400">({provider.api_key_preview})</span>}
          </label>
          {isOllama ? (
            <div className="flex h-10 items-center rounded-lg border border-gray-200 bg-gray-50 px-3 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
              No API key required
            </div>
          ) : (
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={provider.api_key_set ? 'Enter new key to update' : 'Enter API key'}
                className="h-10 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 pr-10 text-sm text-gray-900 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-indigo-500 dark:focus:ring-indigo-950"
              />
              <button
                type="button"
                onClick={() => setShowKey(s => !s)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                title={showKey ? 'Hide API key' : 'Show API key'}
              >
                {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          )}
        </div>

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex h-10 flex-1 items-center justify-center rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? 'Saving...' : isOllama ? 'Enable' : 'Save key'}
          </button>
          <button
            type="button"
            onClick={handleTest}
            disabled={testing}
            className="flex h-10 items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            {testing && <Loader size={14} className="animate-spin" />}
            Test
          </button>
        </div>
      </div>
    </article>
  )
}

function ProviderGrid({ providers, onUpdate }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 lg:gap-5">
      {providers.map(provider => (
        <ProviderCard key={provider.id} provider={provider} onUpdate={onUpdate} />
      ))}
    </div>
  )
}

export default function Models() {
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getProviders()
      .then(data => {
        if (!data || !Array.isArray(data)) {
          toast.error('Invalid response from server')
          setProviders([])
          return
        }
        setProviders(data)
      })
      .catch(error => {
        toast.error(`Failed to load providers: ${error.message || 'Unknown error'}`)
        setProviders([])
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  useEffect(() => { load() }, [load])

  const handleUpdate = async (id, data) => {
    await updateProvider(id, data)
    clearModelStatusCache()
    load()
  }

  const { primaryProviders, secondaryProviders } = useMemo(() => {
    const byId = new Map(providers.map(provider => [provider.id, provider]))
    const primary = PRIMARY_PROVIDER_IDS.map(id => byId.get(id)).filter(Boolean)
    const secondary = providers
      .filter(provider => !PRIMARY_PROVIDER_IDS.includes(provider.id))
      .sort((a, b) => a.name.localeCompare(b.name))
    return { primaryProviders: primary, secondaryProviders: secondary }
  }, [providers])

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-7 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-950 dark:text-white">Models</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Configure provider authentication and verify connectivity.</p>
        </div>
      </div>

      {loading ? (
        <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <Loader size={32} className="animate-spin text-indigo-600" />
        </div>
      ) : providers.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
          <XCircle size={32} className="mx-auto mb-3 opacity-50" />
          <p>No providers available. Check backend connection.</p>
        </div>
      ) : (
        <div className="space-y-8">
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">Primary providers</h2>
            <ProviderGrid providers={primaryProviders} onUpdate={handleUpdate} />
          </section>

          {secondaryProviders.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">Other providers</h2>
              <ProviderGrid providers={secondaryProviders} onUpdate={handleUpdate} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}
