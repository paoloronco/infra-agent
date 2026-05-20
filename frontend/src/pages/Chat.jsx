import React, { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Send, Trash2, Edit2, Check, X, Copy, Bot, User, AlertCircle, Clock, Plus, Paperclip, FileText, FileJson, FileCode, File, Image as ImageIcon, Lock, ShieldAlert, Activity, Wrench, RotateCcw } from 'lucide-react'
import { useApp } from '../context/AppContext'
import { getChats, getChat, updateChat, renameChat, deleteChat, createChat, streamMessage, getSystems, uploadAttachment, getAttachmentUrl, resolveApproval } from '../api'
import ModelPicker, { firstAvailableModel, isKnownModel, isModelAvailable, loadModelStatus } from '../components/ModelPicker'
import AttachmentBar from '../components/AttachmentBar'
import toast from 'react-hot-toast'

function nodeToPlainText(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeToPlainText).join('')
  if (React.isValidElement(node)) return nodeToPlainText(node.props?.children)
  return String(node)
}

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall through to the legacy path for older or permission-restricted browsers.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '-9999px'
  textarea.style.left = '-9999px'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, textarea.value.length)
  try {
    const ok = document.execCommand('copy')
    if (!ok) throw new Error('execCommand copy failed')
  } finally {
    document.body.removeChild(textarea)
  }
}

// ── Code block with copy ──────────────────────────────────────────────────────
function CodeBlock({ language, children }) {
  const [copied, setCopied] = useState(false)
  const resetTimerRef = useRef(null)
  const code = nodeToPlainText(children)

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current)
    }
  }, [])

  const copy = async (event) => {
    event.preventDefault()
    event.stopPropagation()
    try {
      await writeClipboardText(code)
      setCopied(true)
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current)
      resetTimerRef.current = setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Copy failed:', err)
      toast.error('Copy failed')
    }
  }
  return (
    <div className="relative group my-2" data-code-block>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? 'Copied code block' : 'Copy code block'}
        title={copied ? 'Copied' : 'Copy'}
        className="absolute right-2 top-2 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100 transition-opacity
          bg-gray-700 hover:bg-gray-600 text-gray-100 text-xs px-2 py-1 rounded z-10 min-w-[32px]
          focus:outline-none focus:ring-2 focus:ring-indigo-400">
        {copied ? 'Copied' : <Copy size={12} />}
      </button>
      <SyntaxHighlighter style={oneDark} language={language || 'text'}
        customStyle={{ margin: 0, borderRadius: '0.5rem', fontSize: '0.82rem' }}>
        {code}
      </SyntaxHighlighter>
    </div>
  )
}

// ── Typing dots indicator ─────────────────────────────────────────────────────
function TypingDots() {
  return (
    <span className="flex items-center gap-1 py-1">
      {[0, 150, 300].map(delay => (
        <span
          key={delay}
          className="w-2 h-2 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"
          style={{ animationDelay: `${delay}ms`, animationDuration: '1s' }}
        />
      ))}
    </span>
  )
}

// ── Attachment chip inside message bubble ─────────────────────────────────────
function MsgAttachmentChip({ att }) {
  const url = getAttachmentUrl(att.id)
  const ext = (att.name || '').split('.').pop().toLowerCase()

  const icon = att.is_image
    ? <ImageIcon size={12} />
    : ['json', 'yaml', 'yml', 'toml'].includes(ext) ? <FileJson size={12} />
    : ['sh', 'py', 'js', 'ts'].includes(ext) ? <FileCode size={12} />
    : ['txt', 'log', 'md', 'csv'].includes(ext) ? <FileText size={12} />
    : <File size={12} />

  if (att.is_image) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block rounded-lg overflow-hidden border-2 border-white/20 hover:border-white/50 transition-all"
        style={{ maxWidth: 200 }}
        title={att.name}
      >
        <img
          src={url}
          alt={att.name}
          className="block max-h-48 w-auto object-contain bg-black/10"
          onError={e => { e.target.style.display = 'none' }}
        />
      </a>
    )
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      download={att.name}
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs
        bg-white/15 hover:bg-white/25 transition-colors border border-white/20
        text-white/90 max-w-[160px]"
      title={`Open ${att.name}`}
    >
      <span className="flex-shrink-0 opacity-70">{icon}</span>
      <span className="truncate">{att.name}</span>
    </a>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────────
function attachPendingApproval(messages, pendingApproval) {
  const normalizedApproval = normalizeApproval(pendingApproval)
  if (!normalizedApproval?.id) return messages || []
  const msgs = messages || []
  let attached = false
  const next = msgs.map(msg => {
    if (String(msg.id) === String(normalizedApproval.assistant_message_id)) {
      attached = true
      return { ...msg, approval: normalizeApproval(msg.approval) || normalizedApproval }
    }
    return msg
  })
  return attached ? next : msgs
}

function normalizeApproval(approval) {
  if (!approval || typeof approval !== 'object') return null
  const status = String(approval.status || '').trim().toLowerCase()
  const normalizedStatus = ['pending', 'approval_required', 'pending_approval', 'waiting_approval'].includes(status)
    ? 'pending'
    : status
  return { ...approval, status: normalizedStatus || 'pending' }
}

function isApprovalPending(approval) {
  return normalizeApproval(approval)?.status === 'pending'
}

function ApprovalCard({ approval, busy, onResolve, showCommand = false }) {
  const pendingApproval = normalizeApproval(approval)
  const [otherText, setOtherText] = useState('')
  const [showOther, setShowOther] = useState(false)
  const otherInputRef = useRef(null)
  if (!pendingApproval || pendingApproval.status !== 'pending') return null

  const openOther = () => {
    setShowOther(true)
    setTimeout(() => otherInputRef.current?.focus(), 0)
  }

  const submitOther = () => {
    const instructions = otherText.trim()
    if (!instructions) {
      toast.error('Write alternative instructions first')
      setShowOther(true)
      return
    }
    onResolve(pendingApproval, 'other', instructions)
  }

  return (
    <div className="mt-3 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/30 p-3 text-sm">
      <div className="flex items-start gap-2">
        <ShieldAlert size={18} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-amber-900 dark:text-amber-100">Risky action approval</div>
          <div className="mt-1 text-xs text-amber-800 dark:text-amber-200">
            Host: <span className="font-mono">{pendingApproval.system_name || 'unknown'}</span>
            <span className="mx-1">•</span>
            Risk: <span className="font-semibold">{pendingApproval.risk_level || 'high'}</span>
          </div>
          {pendingApproval.reason && (
            <p className="mt-2 text-xs text-amber-800 dark:text-amber-200">{pendingApproval.reason}</p>
          )}
        </div>
      </div>

      {showCommand && (
        <div className="mt-3">
          <CodeBlock language="bash">{`${pendingApproval.command || ''}\n`}</CodeBlock>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => onResolve(pendingApproval, 'approve')}
          className="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-medium">
          APPROVE
        </button>
        <button type="button" disabled={busy} onClick={() => onResolve(pendingApproval, 'deny')}
          className="px-3 py-1.5 rounded-md bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white text-xs font-medium">
          DENY
        </button>
        <button type="button" disabled={busy} onClick={openOther}
          className="px-3 py-2 rounded-md bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-white text-xs font-medium">
          OTHER
        </button>
      </div>

      {showOther && (
        <div className="mt-3 flex flex-col sm:flex-row gap-2">
          <textarea
            ref={otherInputRef}
            value={otherText}
            onChange={e => setOtherText(e.target.value)}
            disabled={busy}
            placeholder="Alternative instructions..."
            rows={3}
            className="min-w-0 flex-1 rounded-md border border-amber-200 dark:border-amber-800 bg-white dark:bg-gray-900 px-3 py-2 text-xs text-gray-900 dark:text-gray-100 outline-none focus:ring-1 focus:ring-amber-500 resize-y"
          />
          <button type="button" disabled={busy || !otherText.trim()} onClick={submitOther}
            className="px-3 py-2 rounded-md bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-white text-xs font-medium self-start sm:self-stretch">
            Send alternative
          </button>
        </div>
      )}
    </div>
  )
}

function AgentProgress({ events = [] }) {
  const visible = (events || []).slice(-5)
  if (visible.length === 0) return null

  const iconFor = (type) => {
    if (type === 'tool_start' || type === 'tool_end') return <Wrench size={12} />
    if (type === 'recovery') return <RotateCcw size={12} />
    return <Activity size={12} />
  }

  return (
    <div className="mt-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-900/40 px-3 py-2 text-[11px] text-gray-600 dark:text-gray-300 space-y-1">
      {visible.map((event, index) => (
        <div key={`${event.type || 'event'}-${event.attempt || 0}-${index}`} className="flex items-start gap-2 min-w-0">
          <span className={`${event.success === false ? 'text-amber-500' : 'text-indigo-500'} shrink-0 mt-0.5`}>
            {iconFor(event.type)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="font-medium">
              {event.attempt ? `Attempt ${event.attempt}: ` : ''}
              {event.message || event.type || 'Working'}
            </span>
            {event.tool && <span className="font-mono"> [{event.tool}]</span>}
            {event.reason && <span className="block truncate text-amber-600 dark:text-amber-300">{event.reason}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

function MessageBubble({ msg, isStreaming, onResolveApproval, approvalBusy }) {
  const isUser = msg.role === 'user'
  const status = msg.status || 'complete'
  const showTypingDots = !isUser && (status === 'pending' || status === 'streaming') && !msg.content
  const showFailedBadge = !isUser && status === 'failed'
  const attachments = msg.attachments || []

  return (
    <div className={`flex gap-3 px-4 py-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-xs
        ${isUser ? 'bg-indigo-600' : showFailedBadge ? 'bg-red-500' : 'bg-gray-600'}`}>
        {isUser ? <User size={14} /> : showFailedBadge ? <AlertCircle size={14} /> : <Bot size={14} />}
      </div>

      <div className="flex flex-col gap-1.5 max-w-[85%] sm:max-w-[80%]">
        {/* Attachment previews (above text, images first then files) */}
        {isUser && attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 justify-end">
            {attachments.map(att => <MsgAttachmentChip key={att.id} att={att} />)}
          </div>
        )}

        {/* Message text bubble */}
        {(msg.content || showTypingDots || !isUser) && (
          <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed
            ${isUser
              ? 'bg-indigo-600 text-white rounded-tr-sm'
              : showFailedBadge
                ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-tl-sm'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-tl-sm'
            } ${isStreaming && msg.content ? 'streaming-cursor' : ''}`}>
            {isUser ? (
              <p className="whitespace-pre-wrap">{msg.content}</p>
            ) : showTypingDots ? (
              <TypingDots />
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ inline, className, children }) {
                    const lang = /language-(\w+)/.exec(className || '')?.[1]
                    const text = nodeToPlainText(children)
                    const isBlock = !inline && (className || text.includes('\n'))
                    return !isBlock
                      ? <code className="bg-gray-200 dark:bg-gray-700 px-1 py-0.5 rounded text-xs font-mono">{children}</code>
                      : <CodeBlock language={lang}>{children}</CodeBlock>
                  },
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
                  h3: ({ children }) => <h3 className="font-semibold mt-3 mb-1">{children}</h3>,
                }}>
                {msg.content || ''}
              </ReactMarkdown>
            )}
          </div>
        )}
        {!isUser && isApprovalPending(msg.approval) && (
          <ApprovalCard
            approval={msg.approval}
            busy={approvalBusy === msg.approval.id}
            onResolve={onResolveApproval}
            showCommand
          />
        )}
        {!isUser && <AgentProgress events={msg.progress || []} />}
      </div>
    </div>
  )
}

// ── Chat list item ────────────────────────────────────────────────────────────
function ChatItem({ chat, active, onSelect, onRename, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(chat.title)

  const save = async () => {
    await onRename(chat.id, title)
    setEditing(false)
  }

  return (
    <div onClick={() => !editing && onSelect(chat.id)}
      className={`group flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer text-sm
        transition-colors
        ${active ? 'bg-indigo-600 text-white' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800'}`}>
      {editing ? (
        <>
          <input value={title} onChange={e => setTitle(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && save()}
            className="flex-1 bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 outline-none"
            autoFocus onClick={e => e.stopPropagation()} />
          <button onClick={e => { e.stopPropagation(); save() }}
            className="text-green-500 hover:text-green-600"><Check size={14} /></button>
          <button onClick={e => { e.stopPropagation(); setEditing(false) }}
            className="text-red-500 hover:text-red-600"><X size={14} /></button>
        </>
      ) : (
        <>
          <span className="flex-1 truncate">{chat.title}</span>
          <div className="hidden group-hover:flex gap-1.5">
            <button onClick={e => { e.stopPropagation(); setEditing(true) }}
              className={`${active ? 'text-white/80 hover:text-white' : 'text-gray-400 hover:text-gray-600 dark:hover:text-white'}`}><Edit2 size={14} /></button>
            <button onClick={e => { e.stopPropagation(); onDelete(chat.id) }}
              className={`${active ? 'text-white/80 hover:text-red-200' : 'text-gray-400 hover:text-red-500'}`}><Trash2 size={14} /></button>
          </div>
        </>
      )}
    </div>
  )
}

// ── Main Chat page ────────────────────────────────────────────────────────────
export default function Chat() {
  const { activeChatId, setActiveChatId } = useApp()
  const [chats, setChats] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  // streaming: true only while we are actively reading an SSE stream for THIS chat
  const [streaming, setStreaming] = useState(false)
  const [approvalBusy, setApprovalBusy] = useState(null)
  const [runtimePendingApproval, setRuntimePendingApproval] = useState(null)
  const [selectedModel, setSelectedModel] = useState('')
  const [modelStatus, setModelStatus] = useState(null)
  const [systems, setSystems] = useState([])
  const [systemsLoading, setSystemsLoading] = useState(true)
  const [systemsError, setSystemsError] = useState(null)
  const [selectedHostId, setSelectedHostId] = useState('')
  const [hostLocked, setHostLocked] = useState(false)
  const [search, setSearch] = useState('')
  const [showChatList, setShowChatList] = useState(false)
  // Attachments: array of { clientId, id, name, mime, localUrl, uploading, error }
  const [attachments, setAttachments] = useState([])
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const fileInputRef = useRef(null)

  // AbortController for the active SSE fetch — aborted on chat switch
  const abortControllerRef = useRef(null)
  // Polling interval ref for pending-message recovery
  const pollingRef = useRef(null)
  // Track which chat we're currently loading (prevents stale setMessages)
  const activeChatIdRef = useRef(activeChatId)
  const chatLoadSeqRef = useRef(0)
  const missingHostNoticeRef = useRef(null)
  activeChatIdRef.current = activeChatId

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const stopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setStreaming(false)
  }, [])

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const handleModelChange = useCallback(async (newModelId) => {
    if (!newModelId) return
    setSelectedModel(newModelId)
    if (!activeChatId) return
    try {
      await updateChat(activeChatId, { model: newModelId })
      setChats(prev => prev.map(c => c.id === activeChatId ? { ...c, model: newModelId } : c))
    } catch (err) {
      console.warn('Failed to persist model change:', err)
    }
  }, [activeChatId])

  const handleHostChange = useCallback(async (hostId) => {
    if (hostLocked) return
    setSelectedHostId(hostId)
    if (!hostId || !activeChatId) return

    try {
      const updatedChat = await updateChat(activeChatId, { target_host_id: hostId })
      setChats(prev => prev.map(c => c.id === activeChatId ? { ...c, ...updatedChat } : c))
      setHostLocked(messages.length > 0)
    } catch (err) {
      setHostLocked(false)
      setSelectedHostId('')
      toast.error(err.response?.data?.detail || 'Failed to save host for this chat')
    }
  }, [activeChatId, hostLocked, messages.length])

  const resolveModel = useCallback((savedModel) => {
    if (!modelStatus) return ''
    if (savedModel && isKnownModel(savedModel) && isModelAvailable(savedModel, modelStatus)) {
      return savedModel
    }
    return firstAvailableModel(modelStatus)
  }, [modelStatus])

  const resolveChatHostId = useCallback((chat) => {
    if (!chat?.target_host_id && !chat?.target_host) return ''
    if (chat.target_host_id && systems.some(s => s.id === chat.target_host_id)) {
      return chat.target_host_id
    }
    if (chat.target_host) {
      return systems.find(s => s.name === chat.target_host)?.id || ''
    }
    return systemsLoading ? (chat.target_host_id || '') : ''
  }, [systems, systemsLoading])

  // ── Attachment handling ──────────────────────────────────────────────────────

  const handleFiles = useCallback(async (files, chatId) => {
    const ALLOWED = new Set([
      'image/jpeg', 'image/png', 'image/gif', 'image/webp',
      'text/plain', 'text/markdown', 'text/csv', 'application/json',
      'application/pdf',
    ])
    const ALLOWED_EXTS = /\.(jpg|jpeg|png|gif|webp|txt|log|json|md|markdown|csv|pdf|yaml|yml|sh|conf|ini)$/i

    for (const file of files) {
      if (file.size > 10 * 1024 * 1024) {
        toast.error(`${file.name}: file too large (max 10 MB)`)
        continue
      }
      if (!ALLOWED.has(file.type) && !ALLOWED_EXTS.test(file.name)) {
        toast.error(`${file.name}: file type not supported`)
        continue
      }

      const clientId = `${Date.now()}-${Math.random()}`
      const isImage = file.type.startsWith('image/')
      const localUrl = isImage ? URL.createObjectURL(file) : null

      // Optimistic add
      setAttachments(prev => [...prev, { clientId, id: null, name: file.name, mime: file.type, localUrl, uploading: true }])

      try {
        const uploaded = await uploadAttachment(chatId, file)
        setAttachments(prev => prev.map(a =>
          a.clientId === clientId
            ? { ...a, id: uploaded.id, uploading: false, localUrl: isImage ? getAttachmentUrl(uploaded.id) : null }
            : a
        ))
      } catch (err) {
        toast.error(`Failed to upload ${file.name}: ${err.message}`)
        setAttachments(prev => prev.filter(a => a.clientId !== clientId))
        if (localUrl) URL.revokeObjectURL(localUrl)
      }
    }
  }, [])

  const removeAttachment = useCallback((clientId) => {
    setAttachments(prev => {
      const att = prev.find(a => a.clientId === clientId)
      if (att?.localUrl && !att.id) URL.revokeObjectURL(att.localUrl)
      return prev.filter(a => a.clientId !== clientId)
    })
  }, [])

  // ── Data loading ─────────────────────────────────────────────────────────────

  const loadChats = useCallback(async () => {
    const data = await getChats()
    setChats(data)
    if (!activeChatIdRef.current && data.length > 0) setActiveChatId(data[0].id)
  }, [setActiveChatId])

  const loadSystems = useCallback(async () => {
    try {
      setSystemsLoading(true)
      setSystemsError(null)
      const data = await getSystems()
      if (!Array.isArray(data)) throw new Error('Invalid systems response')
      setSystems(data)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to load systems'
      setSystemsError(msg)
      setSystems([])
      toast.error(`Systems: ${msg}`)
    } finally {
      setSystemsLoading(false)
    }
  }, [])

  const startPollingForChat = useCallback((chatId) => {
    stopPolling()
    pollingRef.current = setInterval(async () => {
      try {
        const updated = await getChat(chatId)
        if (activeChatIdRef.current !== chatId) {
          stopPolling()
          return
        }
        const pending = updated.pending_approval || null
        const updatedMsgs = attachPendingApproval(updated.messages || [], pending)
        setRuntimePendingApproval(pending)
        setMessages(updatedMsgs)
        const stillPending = updatedMsgs.some(m => m.status === 'pending' || m.status === 'streaming')
        if (!stillPending) {
          stopPolling()
          loadChats()
        }
      } catch (err) {
        console.warn('Chat polling error:', err)
      }
    }, 1000)
  }, [loadChats, stopPolling])

  useEffect(() => {
    loadChats()
    loadSystems()
  }, [loadChats, loadSystems])

  useEffect(() => {
    let cancelled = false
    loadModelStatus({ force: true }).then(status => {
      if (cancelled) return
      setModelStatus(status)
      setSelectedModel(current => (
        current && isModelAvailable(current, status)
          ? current
          : firstAvailableModel(status)
      ))
    })
    return () => { cancelled = true }
  }, [])

  // ── Load chat on switch — detects pending messages and starts recovery polling ──

  useEffect(() => {
    activeChatIdRef.current = activeChatId
    const loadSeq = ++chatLoadSeqRef.current

    if (!activeChatId) {
      setSelectedHostId('')
      setHostLocked(false)
      setRuntimePendingApproval(null)
      setMessages([])
      return
    }

    setSelectedHostId('')
    setHostLocked(false)
    setRuntimePendingApproval(null)

    // Stop previous polling (for the old chat)
    stopPolling()

    getChat(activeChatId).then(chat => {
      // Guard: user may have switched again before this resolved
      if (activeChatIdRef.current !== activeChatId || chatLoadSeqRef.current !== loadSeq) return

      const pending = chat.pending_approval || null
      const msgs = attachPendingApproval(chat.messages || [], pending)
      setRuntimePendingApproval(pending)
      setMessages(msgs)

      // ── Model restore with configured-provider fallback ─────────────────
      if (modelStatus) {
        const savedModel = chat.model || ''
        const resolvedModel = resolveModel(savedModel)
        setSelectedModel(resolvedModel)
        if (resolvedModel !== savedModel) {
          updateChat(activeChatId, { model: resolvedModel }).catch(() => {})
        }
      }

      const chatHostId = resolveChatHostId(chat)
      setSelectedHostId(chatHostId)
      setHostLocked(Boolean(chatHostId && msgs.length > 0))
      if (chat.target_host_missing && !systemsLoading && missingHostNoticeRef.current !== activeChatId) {
        toast.error('The host linked to this chat no longer exists. Select a new host to continue.')
        missingHostNoticeRef.current = activeChatId
      }

      // Recovery: if this chat has a pending/streaming message from a previous session
      // (e.g. user switched away, refreshed, or the SSE was interrupted),
      // poll the DB every second until all pending messages resolve.
      const hasPending = msgs.some(m => m.status === 'pending' || m.status === 'streaming')
      if (hasPending) {
        startPollingForChat(activeChatId)
      }
    }).catch(() => {})
  }, [activeChatId, stopPolling, loadChats, modelStatus, resolveModel, resolveChatHostId, systemsLoading, startPollingForChat])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopStreaming()
      stopPolling()
    }
  }, [stopStreaming, stopPolling])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Chat management ──────────────────────────────────────────────────────────

  const handleNewChat = async () => {
    if (!selectedModel) {
      toast.error('Select a configured model first')
      return
    }
    stopStreaming()
    stopPolling()
    const chat = await createChat({
      title: 'New Chat',
      model: selectedModel,
    })
    chatLoadSeqRef.current += 1
    activeChatIdRef.current = chat.id
    setChats(prev => [chat, ...prev])
    setActiveChatId(chat.id)
    setMessages([])
    setRuntimePendingApproval(null)
    setSelectedHostId('')
    setHostLocked(false)
    setShowChatList(false)
  }

  const handleSelectChat = (id) => {
    if (id === activeChatId) return
    // Abort active SSE reader — the backend AI task continues independently
    stopStreaming()
    stopPolling()
    chatLoadSeqRef.current += 1
    activeChatIdRef.current = id
    setSelectedHostId('')
    setHostLocked(false)
    setRuntimePendingApproval(null)
    setActiveChatId(id)
    setShowChatList(false)
  }

  const handleRename = async (id, title) => {
    await renameChat(id, title)
    setChats(prev => prev.map(c => c.id === id ? { ...c, title } : c))
  }

  const handleDelete = async (id) => {
    const chat = chats.find(c => c.id === id)
    const name = chat?.title || 'this chat'
    if (!window.confirm(`Delete "${name}" and its messages? Any active run will be cancelled.`)) return
    if (id === activeChatId) {
      stopStreaming()
      stopPolling()
    }
    await deleteChat(id)
    setChats(prev => prev.filter(c => c.id !== id))
    if (activeChatId === id) {
      const remaining = chats.filter(c => c.id !== id)
      setActiveChatId(remaining[0]?.id || null)
      setMessages([])
      setRuntimePendingApproval(null)
    }
  }

  // ── Send message ─────────────────────────────────────────────────────────────

  const handleResolveApproval = async (approval, decision, instructions = '') => {
    if (!activeChatId || !approval?.id || approvalBusy) return
    setApprovalBusy(approval.id)
    try {
      const updated = await resolveApproval(activeChatId, approval.id, { decision, instructions })
      const pending = updated.pending_approval || null
      const updatedMsgs = attachPendingApproval(updated.messages || [], pending)
      setRuntimePendingApproval(pending)
      setMessages(updatedMsgs)
      if (updatedMsgs.some(m => m.status === 'pending' || m.status === 'streaming')) {
        startPollingForChat(activeChatId)
      }
      loadChats()
    } catch (err) {
      const detail = err.response?.data?.detail
      const message = typeof detail === 'object' ? detail.message : detail || 'Failed to resolve approval'
      toast.error(message)
    } finally {
      setApprovalBusy(null)
    }
  }

  const handleSend = async () => {
    const pendingApproval = messages.find(m => isApprovalPending(m.approval))?.approval || runtimePendingApproval
    if (pendingApproval) {
      toast.error('Resolve the pending approval before sending another message')
      return
    }
    if (messages.some(m => m.status === 'pending' || m.status === 'streaming')) {
      toast.error('Wait for the current action to finish before sending another message')
      return
    }
    if ((!input.trim() && attachments.length === 0) || streaming) return
    if (!selectedModel) {
      toast.error('Select a configured model first')
      return
    }

    let chatId = activeChatId
    if (!chatId) {
      const chat = await createChat({
        title: 'New Chat',
        model: selectedModel,
        target_host_id: selectedHostId || null,
      })
      chatLoadSeqRef.current += 1
      activeChatIdRef.current = chat.id
      setChats(prev => [chat, ...prev])
      setActiveChatId(chat.id)
      chatId = chat.id
      setHostLocked(!!selectedHostId)
    }

    if (selectedHostId && !hostLocked) {
      setHostLocked(true)
      const updatedChat = await updateChat(chatId, { target_host_id: selectedHostId })
      setChats(prev => prev.map(c => c.id === chatId ? { ...c, ...updatedChat } : c))
    }

    // Upload any attachments that were added before a chat existed
    const pendingUploads = attachments.filter(a => !a.id && !a.uploading)
    if (pendingUploads.length > 0) {
      await handleFiles(pendingUploads.map(a => a._file).filter(Boolean), chatId)
    }

    const content = input.trim() || (attachments.length > 0 ? 'Please analyze the attached file(s).' : '')
    const attachmentIds = attachments.filter(a => a.id && !a.uploading).map(a => a.id)

    setInput('')
    setAttachments([])
    setStreaming(true)

    // Optimistic UI: add user + assistant placeholder immediately with attachment metadata
    const tempUserId = `temp-user-${Date.now()}`
    const tempAssistantId = `temp-assistant-${Date.now()}`
    const optimisticAttachments = attachments
      .filter(a => a.id && !a.uploading)
      .map(a => ({ id: a.id, name: a.name, mime_type: a.mime, is_image: !!a.mime?.startsWith('image/') }))
    setMessages(prev => [
      ...prev,
      { id: tempUserId, role: 'user', content, status: 'complete', attachments: optimisticAttachments },
      { id: tempAssistantId, role: 'assistant', content: '', status: 'pending', attachments: [] },
    ])
    setRuntimePendingApproval(null)

    // Create a new AbortController for this request
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const res = await streamMessage(chatId, content, selectedModel, controller.signal, attachmentIds)
      if (!res.ok) {
        const errorBody = await res.json().catch(() => ({ detail: res.statusText }))
        const detail = errorBody.detail
        const error = new Error(typeof detail === 'object' ? detail.message : detail || 'Failed to send message')
        error.response = { data: errorBody, status: res.status }
        throw error
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let sseBuffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          sseBuffer += decoder.decode(value, { stream: true })
          const events = sseBuffer.split('\n\n')
          sseBuffer = events.pop() || ''

          for (const event of events) {
            const line = event.split('\n').find(l => l.startsWith('data: '))
            if (!line) continue
            try {
              const data = JSON.parse(line.slice(6))

              if (data.token) {
                setMessages(prev => prev.map(m =>
                  m.id === tempAssistantId
                    ? { ...m, content: m.content + data.token, status: 'streaming' }
                    : m
                ))
              }

              if (data.progress) {
                setMessages(prev => prev.map(m =>
                  m.id === tempAssistantId || String(m.id) === String(data.message_id)
                    ? {
                        ...m,
                        status: m.status === 'pending' ? 'streaming' : m.status,
                        progress: [...(m.progress || []), data.progress].slice(-12),
                      }
                    : m
                ))
              }

              if (data.done) {
                setRuntimePendingApproval(null)
                // Replace temp IDs with real DB IDs and mark complete
                setMessages(prev => prev.map(m =>
                  m.id === tempAssistantId
                    ? { ...m, id: data.message_id, status: 'complete', progress: [] }
                    : m
                ))
                loadChats()
              }

              if (data.approval_required) {
                setRuntimePendingApproval(data.approval_required)
                setMessages(prev => prev.map(m =>
                  m.id === tempAssistantId
                    ? {
                        ...m,
                        id: data.message_id,
                        status: 'approval_required',
                        content: data.content || 'Approval required before running this action.',
                        approval: data.approval_required,
                      }
                    : m
                ))
                setStreaming(false)
                loadChats()
              }

              if (data.error) {
                setRuntimePendingApproval(null)
                setMessages(prev => prev.map(m =>
                  m.id === tempAssistantId
                    ? { ...m, content: `⚠️ ${data.error}`, status: 'failed' }
                    : m
                ))
              }
            } catch {
              // Malformed SSE line — skip
            }
          }
        }
      } catch (readErr) {
        if (readErr.name === 'AbortError') {
          // User switched chats — the backend task continues and saves to DB.
          // The new chat's useEffect will handle loading messages there.
          // When user returns to this chat, pending message will be polled.
        } else {
          throw readErr
        }
      }

    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Stream error:', err)
        const detail = err.response?.data?.detail
        const message = typeof detail === 'object'
          ? detail.message
          : detail || 'Failed to send message'
        toast.error(message)
        // Mark the optimistic assistant message as failed
        setMessages(prev => prev.map(m =>
          m.id === tempAssistantId
            ? { ...m, content: message, status: 'failed' }
            : m
        ))
      }
    } finally {
      // Only clear streaming if we're still on the same chat
      if (activeChatIdRef.current === chatId) {
        setStreaming(false)
      }
      abortControllerRef.current = null
    }
  }

  const filteredChats = chats.filter(c =>
    c.title.toLowerCase().includes(search.toLowerCase())
  )

  // Is there any message being processed in the current view?
  const hasPendingMessage = messages.some(m => m.status === 'pending' || m.status === 'streaming')
  const messagePendingApproval = messages.find(m => isApprovalPending(m.approval))?.approval || null
  const pendingApproval = normalizeApproval(messagePendingApproval || runtimePendingApproval)
  const pendingApprovalRenderedInMessage = !!(
    pendingApproval?.id &&
    messages.some(m => isApprovalPending(m.approval) && m.approval?.id === pendingApproval.id)
  )
  const chatBlockedByApproval = !!pendingApproval
  const chatInputBlocked = chatBlockedByApproval || hasPendingMessage

  return (
    <div className="flex h-full overflow-hidden bg-white dark:bg-gray-900 relative">
      {/* ── Left Sidebar (Chat History) ── */}
      <div className={`
        flex flex-col border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900
        md:w-64 md:shrink-0 md:static md:translate-x-0
        fixed inset-y-0 left-0 z-50 w-72
        transition-transform duration-200 ease-in-out
        ${showChatList ? 'translate-x-0 shadow-2xl' : '-translate-x-full'}
      `}>
        <div className="p-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between gap-2 bg-gray-100/50 dark:bg-gray-800/50">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 px-1">History</h2>
          <div className="flex items-center gap-1">
            <button onClick={handleNewChat}
              className="p-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-gray-700"
              title="New Chat">
              <Plus size={16} />
            </button>
            <button onClick={() => setShowChatList(false)}
              className="md:hidden p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800">
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="p-2 border-b border-gray-200 dark:border-gray-700">
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search chats..."
            className="w-full text-xs px-3 py-2 rounded-lg bg-white dark:bg-gray-800
              border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100
              placeholder-gray-400 outline-none focus:ring-1 focus:ring-indigo-500" />
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {filteredChats.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-4">No chats yet</p>
          )}
          {filteredChats.map(chat => (
            <ChatItem key={chat.id} chat={chat}
              active={chat.id === activeChatId}
              onSelect={handleSelectChat}
              onRename={handleRename}
              onDelete={handleDelete} />
          ))}
        </div>
      </div>

      {/* Overlay for mobile */}
      {showChatList && (
        <div
          className="fixed inset-0 z-40 bg-gray-950/40 md:hidden backdrop-blur-[1px]"
          onClick={() => setShowChatList(false)}
        />
      )}

      {/* ── Main area ── */}
      <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-gray-900">
        {/* ── Toolbar ── */}
        <div className="flex items-center gap-x-2 px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-md sticky top-0 z-20 min-h-[52px]">
          {/* History Toggle (mobile) */}
          <button onClick={() => setShowChatList(true)}
            className="p-2 rounded-lg text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 md:hidden shrink-0"
            title="Chat History">
            <Clock size={20} />
          </button>

          {/* New Chat (mobile) */}
          <button onClick={handleNewChat}
            className="p-2 rounded-lg text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 md:hidden shrink-0"
            title="New Chat">
            <Plus size={20} />
          </button>

          <div className="h-6 w-[1px] bg-gray-200 dark:border-gray-700 mx-1 md:hidden" />

          {/* Host Selection */}
          <div className="flex items-center gap-1.5 min-w-0">
            <select
              value={selectedHostId}
              onChange={e => handleHostChange(e.target.value)}
              disabled={hostLocked || systemsLoading || chatInputBlocked}
              className="text-xs sm:text-sm px-2 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-800
                border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100
                outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50 max-w-[120px] sm:max-w-[200px] truncate"
              title={hostLocked ? 'Host is locked for this chat' : systemsLoading ? 'Loading systems...' : 'Select host for this chat'}>
              <option value="">{systemsLoading ? 'Loading...' : 'Auto-detect'}</option>
              {!systemsLoading && systems.length === 0 && (
                <option disabled>No systems configured</option>
              )}
              {systems.map(s => (
                <option key={s.id || s.name} value={s.id}>{s.name}</option>
              ))}
            </select>
            {hostLocked && <Lock size={12} className="text-amber-500 shrink-0" />}
            {systemsError && (
              <button onClick={loadSystems}
                title={`Error: ${systemsError}. Click to retry.`}
                className="text-[10px] text-red-500 hover:text-red-600 shrink-0 px-1">
                <AlertCircle size={14} />
              </button>
            )}
          </div>

          {/* Model Selection */}
          <div className="flex justify-end">
            <ModelPicker
              value={selectedModel}
              onChange={handleModelChange}
              disabled={streaming || chatInputBlocked}
            />
          </div>
        </div>

        {/* ── Messages ── */}
        <div className="flex-1 overflow-y-auto py-3 scrollbar-thin scrollbar-thumb-gray-300 dark:scrollbar-thumb-gray-700">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <Bot size={48} className="text-indigo-200 dark:text-indigo-900/40 mb-4" />
              <h2 className="text-xl font-bold text-gray-800 dark:text-gray-200 mb-2">
                Troubleshooting Agent
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm mb-8">
                Ask me to check systems, services, or logs on your remote hosts.
              </p>
              <div className="grid grid-cols-1 gap-2 w-full max-w-sm">
                {[
                  'Check disk usage on "my-server"',
                  'Is nginx running on "web-prod"?',
                  'Show system resources on "db-host"',
                ].map(s => (
                  <button key={s} onClick={() => setInput(s)}
                    className="text-left text-xs px-4 py-2.5 rounded-xl border border-gray-200
                      dark:border-gray-700 text-gray-600 dark:text-gray-400
                      hover:bg-gray-50 dark:hover:bg-gray-800 transition-all hover:border-indigo-300 dark:hover:border-indigo-900">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <MessageBubble
              key={msg.id || i}
              msg={msg}
              isStreaming={streaming && i === messages.length - 1 && msg.role === 'assistant'}
              onResolveApproval={handleResolveApproval}
              approvalBusy={approvalBusy}
            />
          ))}
          {pendingApproval && !pendingApprovalRenderedInMessage && (
            <div className="px-4 py-3 max-w-4xl">
              <ApprovalCard
                approval={pendingApproval}
                busy={approvalBusy === pendingApproval.id}
                onResolve={handleResolveApproval}
                showCommand
              />
            </div>
          )}
          <div ref={bottomRef} className="h-4" />
        </div>

        {/* ── Input ── */}
        <div
          className="px-3 sm:px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault()
            if (chatInputBlocked) return
            const files = Array.from(e.dataTransfer.files)
            if (files.length > 0) {
              const cid = activeChatId
              if (cid) handleFiles(files, cid)
              else toast('Start a chat first to attach files', { icon: 'ℹ️' })
            }
          }}
        >
          {/* Recovery notice for pending messages from other sessions */}
          {!streaming && hasPendingMessage && (
            <p className="text-xs text-center text-amber-500 dark:text-amber-400 mb-2 animate-pulse">
              ● AI response is being processed in background…
            </p>
          )}

          {chatBlockedByApproval && (
            <p className="text-xs text-center text-amber-600 dark:text-amber-300 mb-2">
              Resolve the approval request above to continue this chat.
            </p>
          )}

          <div className="max-w-4xl mx-auto">
            {/* Attachment chips */}
            <AttachmentBar attachments={attachments} onRemove={removeAttachment} />

            <form onSubmit={e => { e.preventDefault(); handleSend() }} className="flex gap-2 sm:gap-4 items-end">
              {/* Hidden file input */}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/jpeg,image/png,image/gif,image/webp,.txt,.log,.json,.md,.markdown,.csv,.pdf,.yaml,.yml,.sh,.conf,.ini"
                className="hidden"
                onChange={e => {
                  const files = Array.from(e.target.files)
                  e.target.value = ''
                  if (files.length > 0) {
                    const cid = activeChatId
                    if (cid) handleFiles(files, cid)
                    else toast('Start a chat first to attach files', { icon: 'ℹ️' })
                  }
                }}
              />

              {/* Attach button */}
              <button
                type="button"
                disabled={streaming || chatInputBlocked}
                onClick={() => fileInputRef.current?.click()}
                title="Attach file (or drag & drop / paste image)"
                className="p-3 rounded-2xl border border-gray-200 dark:border-gray-700
                  bg-gray-50 dark:bg-gray-800 text-gray-400 hover:text-indigo-500
                  dark:hover:text-indigo-400 hover:border-indigo-300 dark:hover:border-indigo-700
                  disabled:opacity-30 disabled:cursor-not-allowed transition-all shrink-0"
              >
                <Paperclip size={18} />
              </button>

              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                disabled={chatInputBlocked}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                onPaste={e => {
                  const items = Array.from(e.clipboardData?.items || [])
                  const imageItem = items.find(it => it.type.startsWith('image/'))
                  if (imageItem) {
                    e.preventDefault()
                    const file = imageItem.getAsFile()
                    if (file) {
                      const namedFile = new File([file], `paste-${Date.now()}.png`, { type: file.type })
                      const cid = activeChatId
                      if (cid) handleFiles([namedFile], cid)
                      else toast('Start a chat first to attach files', { icon: 'ℹ️' })
                    }
                  }
                }}
                placeholder={chatBlockedByApproval ? 'Approval pending...' : hasPendingMessage ? 'Action running...' : attachments.length > 0 ? 'Add a message or send as-is…' : 'Ask anything…'}
                rows={1}
                className="flex-1 px-4 py-3 rounded-2xl border border-gray-200 dark:border-gray-700
                  bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100
                  placeholder-gray-400 text-sm outline-none focus:ring-2 focus:ring-indigo-500
                  max-h-32 overflow-y-auto transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ resize: 'none' }}
              />

              <button type="submit"
                disabled={!selectedModel || (!input.trim() && attachments.filter(a => a.id).length === 0) || streaming || chatInputBlocked}
                className="p-3 rounded-2xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30
                  disabled:cursor-not-allowed text-white shadow-lg shadow-indigo-200 dark:shadow-none transition-all shrink-0">
                <Send size={20} />
              </button>
            </form>

            <p className="text-[10px] text-center text-gray-400 mt-2">
              AI can make mistakes. Verify critical commands. Drag & drop or paste images to attach.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
