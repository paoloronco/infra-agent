/**
 * ModelPicker — nested flyout menu (macOS / OpenRouter style)
 *
 * Desktop  : two-panel layout — left=providers, right=models for hovered provider
 * Mobile   : accordion — tap provider to expand models below
 *
 * Hover on a provider row (desktop) instantly shows its models in the right panel.
 * Both panels share one container so the mouse can move freely between them
 * without triggering onMouseLeave.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { ChevronDown, ChevronRight, Check, Lock, Settings, Eye } from 'lucide-react'
import { getProviders } from '../api'

// ── Keyframe animation (injected once) ────────────────────────────────────
const STYLE = `
  @keyframes mpSlideIn {
    from { opacity: 0; transform: translateX(6px); }
    to   { opacity: 1; transform: translateX(0);   }
  }
  @keyframes mpFadeIn {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0);    }
  }
  .mp-slide-in  { animation: mpSlideIn 120ms ease-out both; }
  .mp-fade-in   { animation: mpFadeIn  140ms ease-out both; }
  .mp-scroll::-webkit-scrollbar        { width: 4px; }
  .mp-scroll::-webkit-scrollbar-track  { background: transparent; }
  .mp-scroll::-webkit-scrollbar-thumb  { background: rgba(150,150,150,.25); border-radius: 99px; }
  .mp-scroll::-webkit-scrollbar-thumb:hover { background: rgba(150,150,150,.45); }
`

// ── Provider SVG icons ─────────────────────────────────────────────────────
const ICONS = {
  groq({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#F55036" />
        <path d="M15.5 5L7.5 16H13L11 23L21 12H15.5L15.5 5Z" fill="white" />
      </svg>
    )
  },
  openai({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#10a37f" />
        <path fillRule="evenodd" clipRule="evenodd"
          d="M14 7.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13ZM9.5 14a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0Z" fill="white" />
        <circle cx="14" cy="14" r="2" fill="white" />
      </svg>
    )
  },
  anthropic({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#7C3AED" />
        <path d="M14 6.5L20 21.5H17L15.5 17.5H12.5L11 21.5H8L14 6.5ZM14 11.5L12.8 15.5H15.2L14 11.5Z" fill="white" />
      </svg>
    )
  },
  gemini({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#1a73e8" />
        <path d="M14 6.5C14 10.9 10.4 14.5 6 14.5C10.4 14.5 14 18.1 14 22.5C14 18.1 17.6 14.5 22 14.5C17.6 14.5 14 10.9 14 6.5Z" fill="white" />
      </svg>
    )
  },
  deepseek({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#0077B6" />
        <path d="M7 14C7 10.13 10.13 7 14 7C17.87 7 21 10.13 21 14C21 17.87 17.87 21 14 21" stroke="white" strokeWidth="2" strokeLinecap="round" />
        <path d="M14 21C12 21 10 19.5 9 17.5" stroke="white" strokeWidth="2" strokeLinecap="round" />
        <circle cx="14" cy="14" r="2.5" fill="white" />
      </svg>
    )
  },
  mistral_ai({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#FF7000" />
        <rect x="6" y="8" width="4" height="12" fill="white" />
        <rect x="12" y="8" width="4" height="12" fill="white" />
        <rect x="18" y="8" width="4" height="6" fill="white" />
        <rect x="18" y="17" width="4" height="3" fill="white" />
      </svg>
    )
  },
  xai({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#000000" />
        <path d="M8 7L14.5 14.5L8 22H10.5L14.5 17.5L18.5 22H21L14.5 14.5L21 7H18.5L14.5 11.5L10.5 7H8Z" fill="white" />
      </svg>
    )
  },
  perplexity({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#20B2AA" />
        <path d="M14 6L20 10V18L14 22L8 18V10L14 6Z" stroke="white" strokeWidth="1.5" fill="none" />
        <path d="M14 6V22M8 10L20 18M20 10L8 18" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  },
  nvidia({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#76B900" />
        <path d="M6 11.5V10C6 10 9.5 7.5 14 8.5V11.5C14 11.5 11 10.5 9 12V19.5H6V11.5Z" fill="white" />
        <path d="M14 11.5V8.5C14 8.5 19.5 8 22 12V19.5H19V13.5C19 13.5 17.5 11 14 11.5Z" fill="white" />
      </svg>
    )
  },
  openrouter({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#6D28D9" />
        <circle cx="8" cy="14" r="2.5" fill="white" />
        <circle cx="20" cy="9" r="2.5" fill="white" />
        <circle cx="20" cy="19" r="2.5" fill="white" />
        <path d="M10.5 14L17.5 9.5M10.5 14L17.5 18.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  },
  zhipu({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#1352BE" />
        <path d="M8 8H16L12 14H20M12 14L8 20" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  },
  huggingface({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#FFD21E" />
        <circle cx="11" cy="13" r="1.5" fill="#333" />
        <circle cx="17" cy="13" r="1.5" fill="#333" />
        <path d="M10 17C10 17 11.5 19 14 19C16.5 19 18 17 18 17" stroke="#333" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M9 10C9 10 9.5 8 11 8" stroke="#333" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M19 10C19 10 18.5 8 17 8" stroke="#333" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  },
  ollama({ s = 22 }) {
    return (
      <svg width={s} height={s} viewBox="0 0 28 28" fill="none">
        <rect width="28" height="28" rx="7" fill="#1f2937" />
        <ellipse cx="14" cy="12.5" rx="5.5" ry="4.5" stroke="white" strokeWidth="1.5" />
        <circle cx="12" cy="12" r="1.1" fill="white" />
        <circle cx="16" cy="12" r="1.1" fill="white" />
        <path d="M11.5 17C11.5 19.5 12.7 21 14 21C15.3 21 16.5 19.5 16.5 17" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  },
}

function ProviderIcon({ pid, size = 22 }) {
  const C = ICONS[pid]
  if (C) return <C s={size} />
  return (
    <div
      className="rounded-md bg-gray-500 flex items-center justify-center text-white text-[11px] font-bold"
      style={{ width: size, height: size }}
    >
      {(pid?.[0] ?? '?').toUpperCase()}
    </div>
  )
}

// ── Catalog ────────────────────────────────────────────────────────────────
export const PROVIDER_ORDER = [
  'anthropic', 'deepseek', 'gemini', 'groq',
  'huggingface', 'mistral_ai', 'nvidia', 'ollama',
  'openai', 'openrouter', 'perplexity', 'xai', 'zhipu',
]

const PROVIDER_LABEL = {
  groq:        'Groq',
  openai:      'OpenAI',
  anthropic:   'Anthropic',
  gemini:      'Google Gemini',
  deepseek:    'DeepSeek',
  mistral_ai:  'Mistral AI',
  xai:         'xAI',
  perplexity:  'Perplexity',
  openrouter:  'OpenRouter',
  nvidia:      'NVIDIA',
  zhipu:       'Z.AI (GLM)',
  huggingface: 'HuggingFace',
  ollama:      'Ollama',
}

export const MODELS_BY_PROVIDER = {
  groq: [
    { id: 'llama-3.3-70b-versatile',            name: 'Llama 3.3 70B',        tag: 'Recommended' },
    { id: 'llama-4-scout-17b-16e-instruct',      name: 'Llama 4 Scout',        tag: 'New' },
    { id: 'llama-4-maverick-17b-128e-instruct',  name: 'Llama 4 Maverick',     tag: 'New' },
    { id: 'llama-3.1-8b-instant',                name: 'Llama 3.1 8B',         tag: 'Fast' },
    { id: 'gemma2-9b-it',                        name: 'Gemma 2 9B',           tag: '' },
  ],
  openai: [
    { id: 'gpt-5.5',             name: 'GPT-5.5',      tag: 'Top',         vision: true },
    { id: 'gpt-5.4',             name: 'GPT-5.4',      tag: 'Recommended', vision: true },
    { id: 'gpt-5.4-mini',        name: 'GPT-5.4 Mini', tag: 'Fast',        vision: true },
    { id: 'gpt-5.4-nano',        name: 'GPT-5.4 Nano', tag: 'Fastest',     vision: true },
    { id: 'gpt-5.2',             name: 'GPT-5.2',      tag: '',            vision: true },
    { id: 'gpt-5.1',             name: 'GPT-5.1',      tag: '',            vision: true },
    { id: 'gpt-5.1-chat-latest', name: 'GPT-5.1 Chat', tag: '',            vision: true },
    { id: 'gpt-5',               name: 'GPT-5',        tag: '',            vision: true },
    { id: 'gpt-5-mini',          name: 'GPT-5 Mini',   tag: 'Fast',        vision: true },
    { id: 'gpt-5-nano',          name: 'GPT-5 Nano',   tag: 'Fastest',     vision: true },
    { id: 'gpt-4.1',             name: 'GPT-4.1',      tag: '',            vision: true },
    { id: 'gpt-4.1-mini',        name: 'GPT-4.1 Mini', tag: 'Fast',        vision: true },
    { id: 'gpt-4.1-nano',        name: 'GPT-4.1 Nano', tag: 'Fastest',     vision: true },
    { id: 'gpt-4o',              name: 'GPT-4o',       tag: 'Vision',      vision: true },
    { id: 'gpt-4o-mini',         name: 'GPT-4o Mini',  tag: 'Fast',        vision: true },
    { id: 'o3',                  name: 'o3',           tag: 'Reasoning' },
    { id: 'o4-mini',             name: 'o4-mini',      tag: 'Reasoning' },
  ],
  anthropic: [
    { id: 'claude-opus-4-7',            name: 'Claude Opus 4.7',    tag: 'Top',         vision: true },
    { id: 'claude-sonnet-4-6',          name: 'Claude Sonnet 4.6',  tag: 'Recommended', vision: true },
    { id: 'claude-haiku-4-5-20251001',  name: 'Claude Haiku 4.5',   tag: 'Fast',        vision: true },
    { id: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet',  tag: 'Vision',      vision: true },
    { id: 'claude-3-5-haiku-20241022',  name: 'Claude 3.5 Haiku',   tag: 'Vision',      vision: true },
  ],
  gemini: [
    { id: 'gemini-2.5-pro',   name: 'Gemini 2.5 Pro',   tag: 'Recommended', vision: true },
    { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash',  tag: 'Fast',        vision: true },
    { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash',  tag: 'Vision',      vision: true },
    { id: 'gemini-1.5-pro',   name: 'Gemini 1.5 Pro',    tag: 'Vision',      vision: true },
    { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash',  tag: 'Vision',      vision: true },
  ],
  deepseek: [
    { id: 'deepseek-chat',      name: 'DeepSeek V3',   tag: 'Recommended' },
    { id: 'deepseek-reasoner',  name: 'DeepSeek R1',   tag: 'Reasoning' },
  ],
  mistral_ai: [
    { id: 'mistral-large-latest', name: 'Mistral Large', tag: 'Recommended' },
    { id: 'mistral-small-latest', name: 'Mistral Small', tag: 'Fast' },
    { id: 'codestral-latest',     name: 'Codestral',     tag: 'New' },
  ],
  xai: [
    { id: 'grok-3',             name: 'Grok 3',        tag: 'Recommended' },
    { id: 'grok-3-fast',        name: 'Grok 3 Fast',   tag: 'Fast' },
    { id: 'grok-2-vision-1212', name: 'Grok 2 Vision', tag: 'Vision', vision: true },
  ],
  perplexity: [
    { id: 'sonar',            name: 'Sonar',            tag: 'Search' },
    { id: 'sonar-pro',        name: 'Sonar Pro',        tag: 'Recommended' },
    { id: 'sonar-reasoning',  name: 'Sonar Reasoning',  tag: 'Reasoning' },
  ],
  openrouter: [
    { id: 'google/gemini-2.5-pro-preview-05-06',    name: 'Gemini 2.5 Pro',        tag: 'Recommended', vision: true },
    { id: 'openai/gpt-4.1',                         name: 'GPT-4.1',               tag: 'Fast',        vision: true },
    { id: 'anthropic/claude-opus-4-5',              name: 'Claude Opus 4',         tag: 'Top' },
    { id: 'meta-llama/llama-3.3-70b-instruct:free', name: 'Llama 3.3 70B (free)',  tag: 'Free' },
    { id: 'deepseek/deepseek-r1:free',              name: 'DeepSeek R1 (free)',    tag: 'Free' },
  ],
  nvidia: [
    { id: 'nvidia/llama-3.3-nemotron-super-49b-v1', name: 'Nemotron 49B',  tag: 'Recommended' },
    { id: 'meta/llama-3.3-70b-instruct',            name: 'Llama 3.3 70B', tag: 'Fast' },
  ],
  zhipu: [
    { id: 'glm-4-plus',  name: 'GLM-4 Plus',  tag: 'Recommended' },
    { id: 'glm-4v-plus', name: 'GLM-4V Plus', tag: 'Vision',      vision: true },
    { id: 'glm-4-flash', name: 'GLM-4 Flash', tag: 'Fast' },
  ],
  huggingface: [
    { id: 'meta-llama/Llama-3.3-70B-Instruct',        name: 'Llama 3.3 70B', tag: 'Recommended' },
    { id: 'Qwen/Qwen2.5-72B-Instruct',                name: 'Qwen 2.5 72B',  tag: 'Fast' },
    { id: 'mistralai/Mixtral-8x7B-Instruct-v0.1',     name: 'Mixtral 8x7B',  tag: '' },
  ],
  ollama: [
    { id: 'llama3.2',          name: 'Llama 3.2',       tag: '' },
    { id: 'llama3.1',          name: 'Llama 3.1',       tag: '' },
    { id: 'qwen2.5',           name: 'Qwen 2.5',        tag: '' },
    { id: 'qwen2.5-coder',     name: 'Qwen 2.5 Coder',  tag: 'New' },
    { id: 'mistral',           name: 'Mistral',         tag: '' },
    { id: 'codellama',         name: 'CodeLlama',       tag: '' },
    { id: 'phi3',              name: 'Phi-3',           tag: '' },
    { id: 'phi4',              name: 'Phi-4',           tag: 'New' },
    { id: 'gemma2',            name: 'Gemma 2',         tag: '' },
    { id: 'deepseek-coder',    name: 'DeepSeek Coder',  tag: '' },
    { id: 'deepseek-r1',       name: 'DeepSeek R1',     tag: 'Reasoning' },
  ],
}

export function isKnownModel(modelId) {
  return Object.values(MODELS_BY_PROVIDER).flat().some(m => m.id === modelId)
}

// ── Tag badge styles ───────────────────────────────────────────────────────
const TAG_CLS = {
  Recommended: 'bg-indigo-50 text-indigo-600 ring-indigo-200 dark:bg-indigo-950/60 dark:text-indigo-300 dark:ring-indigo-800',
  New:         'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:ring-emerald-800',
  Fast:        'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:ring-amber-800',
  Fastest:     'bg-orange-50 text-orange-700 ring-orange-200 dark:bg-orange-950/60 dark:text-orange-300 dark:ring-orange-800',
  Reasoning:   'bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-950/60 dark:text-violet-300 dark:ring-violet-800',
  Top:         'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:ring-rose-800',
  Vision:      'bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-950/60 dark:text-sky-300 dark:ring-sky-800',
  Search:      'bg-cyan-50 text-cyan-700 ring-cyan-200 dark:bg-cyan-950/60 dark:text-cyan-300 dark:ring-cyan-800',
  Free:        'bg-lime-50 text-lime-700 ring-lime-200 dark:bg-lime-950/60 dark:text-lime-300 dark:ring-lime-800',
  Chat:        'bg-teal-50 text-teal-700 ring-teal-200 dark:bg-teal-950/60 dark:text-teal-300 dark:ring-teal-800',
  Legacy:      'bg-gray-100 text-gray-500 ring-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:ring-gray-700',
}

function Tag({ label }) {
  if (!label) return null
  return (
    <span className={`
      flex-shrink-0 text-[10px] font-semibold leading-none
      px-1.5 py-[3px] rounded-[4px]
      ring-1 ring-inset
      ${TAG_CLS[label] ?? 'bg-gray-100 text-gray-500 ring-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:ring-gray-700'}
    `}>
      {label}
    </span>
  )
}

// ── Provider status cache ──────────────────────────────────────────────────
let _cache = null, _cacheAt = 0
const CACHE_TTL = 60_000

function providerIsConfigured(provider) {
  if (!provider) return false
  if (provider.id === 'ollama') return !!provider.enabled
  return !!provider.api_key_set
}

function buildStatus(providers) {
  const r = {}
  for (const p of providers) r[p.id] = { ok: providerIsConfigured(p) }
  return r
}

function providerSortLabel(pid) {
  return (PROVIDER_LABEL[pid] || pid).toLowerCase()
}

function configuredFirstProviderOrder(status) {
  return [...PROVIDER_ORDER].sort((a, b) => {
    const aOk = !!status?.[a]?.ok
    const bOk = !!status?.[b]?.ok
    if (aOk !== bOk) return aOk ? -1 : 1
    return providerSortLabel(a).localeCompare(providerSortLabel(b))
  })
}

export function clearModelStatusCache() {
  _cache = null
  _cacheAt = 0
}

export async function loadModelStatus({ force = false } = {}) {
  if (!force && _cache && Date.now() - _cacheAt < CACHE_TTL) return _cache
  try {
    const ps = await getProviders()
    const r = buildStatus(ps)
    _cache = r; _cacheAt = Date.now(); return r
  } catch { return _cache ?? {} }
}

// ── Helpers ────────────────────────────────────────────────────────────────
export function findProvider(modelId) {
  for (const [pid, ms] of Object.entries(MODELS_BY_PROVIDER))
    if (ms.some(m => m.id === modelId)) return pid
  return null
}
function findModel(modelId) {
  for (const ms of Object.values(MODELS_BY_PROVIDER)) {
    const m = ms.find(m => m.id === modelId)
    if (m) return m
  }
  return { id: modelId, name: modelId, tag: '' }
}

export function isModelAvailable(modelId, status) {
  const pid = findProvider(modelId)
  return !!pid && !!status?.[pid]?.ok
}

export function firstAvailableModel(status) {
  for (const pid of configuredFirstProviderOrder(status)) {
    if (status?.[pid]?.ok && MODELS_BY_PROVIDER[pid]?.length) {
      return MODELS_BY_PROVIDER[pid][0].id
    }
  }
  return ''
}

function firstAvailableProvider(status) {
  return configuredFirstProviderOrder(status).find(pid => status?.[pid]?.ok && MODELS_BY_PROVIDER[pid]?.length) || null
}

// ── Main component ─────────────────────────────────────────────────────────
export default function ModelPicker({ value, onChange, disabled = false }) {
  const [open,        setOpen]        = useState(false)
  const [visible,     setVisible]     = useState(false)   // drives CSS animation
  const [activePid,   setActivePid]   = useState(null)    // hovered provider (desktop)
  const [expandPid,   setExpandPid]   = useState(null)    // tapped provider (mobile)
  const [status,      setStatus]      = useState(null)
  const [pos,         setPos]         = useState({})
  const [mobile,      setMobile]      = useState(() => window.innerWidth < 640)
  // true when available horizontal space is too narrow for two-panel layout
  const [forceMobile, setForceMobile] = useState(false)

  const wrapRef  = useRef(null)
  const btnRef   = useRef(null)
  const closeRef = useRef(null)
  const rPanRef  = useRef(null)

  const curPid   = findProvider(value)
  const curModel = value && isModelAvailable(value, status) ? findModel(value) : null
  const selectedLabel = curModel?.name || 'Select model'

  // ── Compute fixed position from current button rect ──────────────────────
  const calcPos = useCallback(() => {
    if (!btnRef.current) return
    const r  = btnRef.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const GAP = 6   // gap between button and dropdown
    const EDGE = 8  // min distance from viewport edges

    // ── Width ──────────────────────────────────────────────────────────────
    // Right-align the dropdown to the button's right edge.
    // The dropdown must not extend past the left viewport margin (EDGE).
    // This naturally prevents overlap with any sidebar on the left.
    const maxWidthLeft  = r.right - EDGE          // space from left edge to button's right
    const maxWidthRight = vw - r.left + r.width - EDGE  // space if left-aligned
    const desiredW = vw < 640 ? Math.min(vw - EDGE * 2, 340) : 380
    const width = Math.max(240, Math.min(desiredW, maxWidthLeft))

    // ── Horizontal (fixed coordinates) ────────────────────────────────────
    // Prefer right-aligned to button; clamp so it never exits the viewport.
    let left = r.right - width
    left = Math.max(EDGE, Math.min(left, vw - width - EDGE))

    // ── Vertical (fixed coordinates) ──────────────────────────────────────
    const spaceBelow = vh - r.bottom - EDGE
    const spaceAbove = r.top - EDGE
    const flipUp = spaceBelow < 240 && spaceAbove > spaceBelow

    setPos({
      position: 'fixed',
      left,
      width,
      ...(flipUp
        ? { bottom: vh - r.top + GAP, top: 'auto' }
        : { top: r.bottom + GAP,     bottom: 'auto' }),
    })

    // Force accordion layout when the available width is too narrow
    // for the two-panel design (left panel ~148px + right panel min ~120px)
    setForceMobile(width < 300)
  }, [])

  // Detect mobile resize (always)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 640)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])

  useEffect(() => {
    let cancelled = false
    loadModelStatus().then(s => { if (!cancelled) setStatus(s) })
    return () => { cancelled = true }
  }, [])

  // Recompute position on resize/scroll while open
  useEffect(() => {
    if (!open) return
    const recalc = () => calcPos()
    window.addEventListener('resize', recalc)
    window.addEventListener('scroll', recalc, true)
    return () => {
      window.removeEventListener('resize', recalc)
      window.removeEventListener('scroll', recalc, true)
    }
  }, [open, calcPos])

  // ── Open ──────────────────────────────────────────────────────────────────
  const open_ = useCallback(() => {
    clearTimeout(closeRef.current)
    calcPos()
    const pid = isModelAvailable(value, status)
      ? findProvider(value)
      : firstAvailableProvider(status) || curPid || PROVIDER_ORDER[0]
    setActivePid(pid)
    setExpandPid(null)
    setOpen(true)
    loadModelStatus({ force: true }).then(s => {
      setStatus(s)
      setActivePid(current => {
        if (current && s[current]?.ok) return current
        return firstAvailableProvider(s) || curPid || PROVIDER_ORDER[0]
      })
    })
    requestAnimationFrame(() => setVisible(true))
  }, [value, status, curPid, calcPos])

  // ── Close ───────────────────────────────────────────────────────────────
  const close_ = useCallback(() => {
    setVisible(false)
    closeRef.current = setTimeout(() => {
      setOpen(false)
      setActivePid(null)
    }, 150)
  }, [])

  const toggle = useCallback(() => (open ? close_() : open_()), [open, open_, close_])

  // Outside pointer / Escape
  useEffect(() => {
    if (!open) return
    const onPtr = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) close_() }
    const onKey = e => { if (e.key === 'Escape') { close_(); btnRef.current?.focus() } }
    document.addEventListener('pointerdown', onPtr)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPtr)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close_])

  // Scroll right panel to selected model
  useEffect(() => {
    if (visible && rPanRef.current) {
      const el = rPanRef.current.querySelector('[data-selected="true"]')
      el?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
    }
  }, [visible, activePid])

  const isOk = pid => !!status?.[pid]?.ok

  const select = useCallback((modelId, pid) => {
    if (!isOk(pid)) return
    onChange(modelId)
    close_()
    btnRef.current?.focus()
  }, [onChange, close_, status]) // eslint-disable-line

  // ── Render ─────────────────────────────────────────────────────────────
  const models = MODELS_BY_PROVIDER[activePid] || []
  const orderedProviders = configuredFirstProviderOrder(status)

  return (
    <>
      {/* Inject keyframes once */}
      <style>{STYLE}</style>

      <div ref={wrapRef} className="relative flex-shrink-0">

        {/* ── Trigger ──────────────────────────────────────────────────── */}
        <button
          ref={btnRef}
          type="button"
          disabled={disabled}
          onClick={toggle}
          aria-haspopup="listbox"
          aria-expanded={open}
          title={curModel && curPid ? `${PROVIDER_LABEL[curPid] ?? curPid} · ${curModel.name}` : 'Select model'}
          className={[
            'group flex items-center gap-2 h-8 pl-2 pr-2.5 rounded-lg border select-none',
            'bg-white dark:bg-gray-800 transition-colors duration-100',
            open
              ? 'border-indigo-400 dark:border-indigo-500 ring-1 ring-inset ring-indigo-200 dark:ring-indigo-800'
              : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600',
            disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
          ].join(' ')}
        >
          {curModel && curPid ? <ProviderIcon pid={curPid} size={18} /> : <Settings size={18} className="text-gray-400" />}
          <span className="text-[13px] font-medium text-gray-800 dark:text-gray-100 leading-none truncate
            max-w-[90px] sm:max-w-[130px] md:max-w-[160px]">
            {selectedLabel}
          </span>
          <ChevronDown
            size={13}
            className={`flex-shrink-0 text-gray-400 transition-transform duration-150
              ${open ? 'rotate-180 text-indigo-500' : 'group-hover:text-gray-600 dark:group-hover:text-gray-300'}`}
          />
        </button>

        {/* ── Dropdown ─────────────────────────────────────────────────── */}
        {open && (
          <div
            style={pos}
            className={[
              'z-[9999]',
              'bg-white dark:bg-gray-900',
              'border border-gray-200 dark:border-gray-700',
              'rounded-xl shadow-2xl shadow-black/15 dark:shadow-black/50',
              'overflow-hidden flex flex-col',
              'transition-[opacity,transform] duration-150 ease-out',
              visible ? 'opacity-100 translate-y-0 mp-fade-in' : 'opacity-0 -translate-y-2',
            ].join(' ')}
          >
            {/* ── Desktop: two-panel / Mobile or narrow: accordion ─────────── */}
            {!(mobile || forceMobile) ? (
              <div className="flex" style={{ maxHeight: Math.min(400, window.innerHeight * 0.7) }}>

                {/* LEFT — provider list */}
                <div className="w-[148px] flex-shrink-0 border-r border-gray-100 dark:border-gray-800 py-1.5 overflow-y-auto mp-scroll">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 px-4 pt-1 pb-2">
                    Provider
                  </p>
                  {orderedProviders.map(pid => {
                    const ok      = isOk(pid)
                    const isActive = activePid === pid

                    return (
                      <div
                        key={pid}
                        role="button"
                        tabIndex={ok ? 0 : -1}
                        onMouseEnter={() => ok && setActivePid(pid)}
                        onClick={() => ok && setActivePid(pid)}
                        title={!ok ? 'API key not configured — go to Models settings' : ''}
                        className={[
                          'flex items-center gap-2.5 mx-1.5 px-2.5 py-2.5 rounded-lg',
                          'transition-colors duration-75 cursor-default',
                          ok ? 'cursor-pointer' : 'opacity-35 cursor-not-allowed',
                          ok && isActive
                            ? 'bg-gray-100 dark:bg-gray-800'
                            : ok ? 'hover:bg-gray-50 dark:hover:bg-gray-800/70' : '',
                        ].join(' ')}
                      >
                        <span className={ok ? 'opacity-100' : 'opacity-60'}>
                          <ProviderIcon pid={pid} size={20} />
                        </span>
                        <span className={[
                          'flex-1 text-sm leading-tight truncate',
                          isActive && ok
                            ? 'font-semibold text-gray-900 dark:text-white'
                            : 'font-medium text-gray-600 dark:text-gray-400',
                        ].join(' ')}>
                          {PROVIDER_LABEL[pid]}
                        </span>
                        {ok
                          ? <ChevronRight size={13} className={isActive ? 'text-gray-500 dark:text-gray-300' : 'text-gray-300 dark:text-gray-600'} />
                          : <Lock size={12} className="text-gray-400 flex-shrink-0" />
                        }
                      </div>
                    )
                  })}
                </div>

                {/* RIGHT — models panel */}
                <div className="flex-1 flex flex-col min-w-0">
                  {/* Provider header in right panel */}
                  <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-800 flex-shrink-0">
                    <ProviderIcon pid={activePid} size={16} />
                    <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 flex-1">
                      {PROVIDER_LABEL[activePid]}
                    </span>
                    {isOk(activePid) ? (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full
                        bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400
                        ring-1 ring-inset ring-emerald-200 dark:ring-emerald-800">
                        Ready
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full
                        bg-gray-100 dark:bg-gray-800 text-gray-400
                        ring-1 ring-inset ring-gray-200 dark:ring-gray-700">
                        <Lock size={9} /> No key
                      </span>
                    )}
                  </div>

                  {/* Model list */}
                  <div
                    ref={rPanRef}
                    key={activePid}
                    className="flex-1 overflow-y-auto mp-scroll mp-slide-in"
                  >
                    {!isOk(activePid) ? (
                      <div className="flex flex-col items-center justify-center py-8 px-4 text-center gap-2">
                        <Lock size={20} className="text-gray-300 dark:text-gray-600" />
                        <p className="text-sm text-gray-400 dark:text-gray-500">API key not configured</p>
                        <a href="/models" onClick={close_}
                          className="text-xs text-indigo-500 hover:underline">
                          Configure in Models →
                        </a>
                      </div>
                    ) : (
                      <div className="py-1">
                        {models.map(model => {
                          const sel = value === model.id
                          return (
                            <button
                              key={model.id}
                              type="button"
                              data-selected={sel}
                              onClick={() => select(model.id, activePid)}
                              className={[
                                'w-full flex items-center gap-2.5 px-4 py-2.5 text-left',
                                'transition-colors duration-75 cursor-pointer',
                                sel
                                  ? 'bg-indigo-50 dark:bg-indigo-950/50'
                                  : 'hover:bg-gray-50 dark:hover:bg-gray-800/60',
                              ].join(' ')}
                            >
                              {/* Checkmark column */}
                              <span className="w-4 flex-shrink-0 flex items-center">
                                {sel && <Check size={13} className="text-indigo-600 dark:text-indigo-400" />}
                              </span>
                              {/* Name */}
                              <span className={[
                                'flex-1 text-sm leading-tight truncate',
                                sel
                                  ? 'font-semibold text-indigo-700 dark:text-indigo-300'
                                  : 'font-normal text-gray-800 dark:text-gray-100',
                              ].join(' ')}>
                                {model.name}
                              </span>
                              {model.vision && model.tag !== 'Vision' && (
                                <Eye size={11} className="flex-shrink-0 text-sky-400 dark:text-sky-500" title="Supports image input" />
                              )}
                              <Tag label={model.tag} />
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              /* ── Mobile: accordion ─────────────────────────────────────── */
              <div
                className="overflow-y-auto mp-scroll"
                style={{ maxHeight: Math.min(440, window.innerHeight * 0.72) }}
              >
                <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500 px-4 pt-3 pb-1">
                  Select a model
                </p>
                {orderedProviders.map(pid => {
                  const ok   = isOk(pid)
                  const open = expandPid === pid
                  const pmod = MODELS_BY_PROVIDER[pid] || []

                  return (
                    <div key={pid}>
                      <button
                        type="button"
                        disabled={!ok}
                        onClick={() => ok && setExpandPid(open ? null : pid)}
                        title={!ok ? 'API key not configured' : ''}
                        className={[
                          'w-full flex items-center gap-3 px-4 py-3 text-left',
                          'transition-colors duration-75',
                          ok ? 'cursor-pointer' : 'opacity-35 cursor-not-allowed',
                          ok && open
                            ? 'bg-gray-50 dark:bg-gray-800'
                            : ok ? 'hover:bg-gray-50 dark:hover:bg-gray-800/60' : '',
                        ].join(' ')}
                      >
                        <ProviderIcon pid={pid} size={22} />
                        <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-100">
                          {PROVIDER_LABEL[pid]}
                        </span>
                        {ok
                          ? <ChevronDown size={14} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
                          : <Lock size={13} className="text-gray-400" />
                        }
                      </button>

                      {open && ok && (
                        <div className="bg-gray-50/70 dark:bg-gray-800/40 border-t border-b border-gray-100 dark:border-gray-800 mp-fade-in">
                          {pmod.map(model => {
                            const sel = value === model.id
                            return (
                              <button
                                key={model.id}
                                type="button"
                                onClick={() => select(model.id, pid)}
                                className={[
                                  'w-full flex items-center gap-2.5 pl-[54px] pr-4 py-2.5 text-left',
                                  'transition-colors duration-75',
                                  sel
                                    ? 'bg-indigo-50 dark:bg-indigo-950/50'
                                    : 'hover:bg-white dark:hover:bg-gray-700/50',
                                ].join(' ')}
                              >
                                <span className="w-4 flex-shrink-0 flex items-center">
                                  {sel && <Check size={13} className="text-indigo-600 dark:text-indigo-400" />}
                                </span>
                                <span className={[
                                  'flex-1 text-sm leading-tight',
                                  sel
                                    ? 'font-semibold text-indigo-700 dark:text-indigo-300'
                                    : 'text-gray-700 dark:text-gray-200',
                                ].join(' ')}>
                                  {model.name}
                                </span>
                                {model.vision && model.tag !== 'Vision' && (
                                  <Eye size={11} className="flex-shrink-0 text-sky-400 dark:text-sky-500" title="Supports image input" />
                                )}
                                <Tag label={model.tag} />
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── Footer ─────────────────────────────────────────────────── */}
            <div className="flex items-center gap-2 px-4 py-2 border-t border-gray-100 dark:border-gray-800
              bg-gray-50/60 dark:bg-gray-800/30 flex-shrink-0">
              <Settings size={11} className="text-gray-400 flex-shrink-0" />
              <span className="text-[11px] text-gray-400 dark:text-gray-500">
                Configure keys in{' '}
                <a href="/models" onClick={close_}
                  className="text-indigo-500 hover:text-indigo-600 dark:hover:text-indigo-400 font-medium hover:underline">
                  Models
                </a>
              </span>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
