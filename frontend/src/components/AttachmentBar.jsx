/**
 * AttachmentBar — shows uploaded attachment chips above the message input.
 * Parent (Chat.jsx) owns upload state; this component only renders + removes.
 */
import React from 'react'
import { X, FileText, FileJson, FileCode, File, Image } from 'lucide-react'
import { getAttachmentUrl } from '../api'

function fileIcon(mime, name) {
  if (mime?.startsWith('image/')) return <Image size={13} />
  const ext = (name || '').split('.').pop().toLowerCase()
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) return <FileJson size={13} />
  if (['sh', 'py', 'js', 'ts', 'conf', 'ini'].includes(ext)) return <FileCode size={13} />
  if (['txt', 'log', 'md', 'csv'].includes(ext)) return <FileText size={13} />
  return <File size={13} />
}

function AttachmentChip({ att, onRemove }) {
  const isImage = att.mime?.startsWith('image/')
  const url = att.id ? getAttachmentUrl(att.id) : att.localUrl

  return (
    <div className={[
      'relative flex items-center gap-1.5 rounded-lg border text-xs',
      'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700',
      isImage ? 'p-0 overflow-hidden' : 'px-2 py-1.5',
    ].join(' ')}
      style={{ maxWidth: 160 }}
    >
      {isImage ? (
        /* Image thumbnail */
        <div className="relative w-14 h-14 flex-shrink-0">
          <img
            src={url}
            alt={att.name}
            className="w-full h-full object-cover"
            onError={e => { e.target.style.display = 'none' }}
          />
          {att.uploading && (
            <div className="absolute inset-0 bg-white/60 dark:bg-gray-900/60 flex items-center justify-center">
              <span className="text-[10px] text-gray-500 animate-pulse">…</span>
            </div>
          )}
        </div>
      ) : (
        <>
          <span className="text-gray-400 flex-shrink-0">{fileIcon(att.mime, att.name)}</span>
          <span className="truncate text-gray-600 dark:text-gray-300 leading-tight" style={{ maxWidth: 100 }}>
            {att.name}
          </span>
          {att.uploading && (
            <span className="text-[10px] text-indigo-400 flex-shrink-0 animate-pulse">↑</span>
          )}
        </>
      )}

      {/* Remove button */}
      <button
        type="button"
        onClick={() => onRemove(att.clientId)}
        className={[
          'flex-shrink-0 rounded-full p-0.5 transition-colors',
          isImage
            ? 'absolute top-0.5 right-0.5 bg-gray-900/60 text-white hover:bg-gray-900/80'
            : 'text-gray-400 hover:text-red-500 dark:hover:text-red-400 ml-0.5',
        ].join(' ')}
        title="Remove"
      >
        <X size={10} />
      </button>
    </div>
  )
}

export default function AttachmentBar({ attachments, onRemove }) {
  if (!attachments.length) return null

  return (
    <div className="flex flex-wrap gap-2 mb-2 px-1">
      {attachments.map(att => (
        <AttachmentChip key={att.clientId} att={att} onRemove={onRemove} />
      ))}
    </div>
  )
}
