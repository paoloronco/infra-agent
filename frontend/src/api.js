import axios from 'axios'

export const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
export const apiUrl = (path) => `${API_BASE_URL}${path}`
export const API = axios.create({ baseURL: API_BASE_URL })

// Attach JWT token to every request
API.interceptors.request.use(config => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// On 401, clear token so App re-renders the Login page
API.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      window.dispatchEvent(new Event('auth:logout'))
    }
    return Promise.reject(err)
  }
)

// Chat
export const getChats = () => API.get('/api/chats').then(r => r.data)
export const createChat = (data) => API.post('/api/chats', data).then(r => r.data)
export const getChat = (id) => API.get(`/api/chats/${id}`).then(r => r.data)
export const updateChat = (id, data) => API.patch(`/api/chats/${id}`, data).then(r => r.data)
export const renameChat = (id, title) => API.patch(`/api/chats/${id}`, { title }).then(r => r.data)
export const deleteChat = (id) => API.delete(`/api/chats/${id}`).then(r => r.data)
export const getAvailableModels = () => API.get('/api/chats/models/available').then(r => r.data)
export const resolveApproval = (chatId, approvalId, data) =>
  API.post(`/api/chats/${chatId}/approvals/${approvalId}`, data).then(r => r.data)

// Models
export const getProviders = () => API.get('/api/models/providers').then(r => r.data)
export const updateProvider = (id, data) => API.put(`/api/models/providers/${id}`, data).then(r => r.data)
export const testProvider = (id) => API.post(`/api/models/providers/${id}/test`).then(r => r.data)

// Usage
export const getUsageSummary = () => API.get('/api/usage/summary').then(r => r.data)
export const getUsageByModel = () => API.get('/api/usage/by-model').then(r => r.data)
export const getUsageDaily = (days) => API.get(`/api/usage/daily?days=${days}`).then(r => r.data)

// Logs
export const getLogs = (params = {}) => API.get('/api/logs', { params }).then(r => r.data)
export const getLogStats = (params = {}) => API.get('/api/logs/stats', { params }).then(r => r.data)
export const clearLogs = () => API.delete('/api/logs').then(r => r.data)
export const exportLogs = (params = {}) => API.get('/api/logs/export', { params, responseType: 'blob' }).then(r => r.data)

// Cron
export const getCronJobs = () => API.get('/api/cron').then(r => r.data)
export const createCronJob = (data) => API.post('/api/cron', data).then(r => r.data)
export const updateCronJob = (id, data) => API.patch(`/api/cron/${id}`, data).then(r => r.data)
export const deleteCronJob = (id) => API.delete(`/api/cron/${id}`).then(r => r.data)
export const runCronJob = (id) => API.post(`/api/cron/${id}/run`).then(r => r.data)

// SSH
export const getSshKeys = () => API.get('/ssh-keys').then(r => r.data)
export const createSshKey = (data) => API.post('/ssh-key', data).then(r => r.data)
export const deleteSshKey = (id) => API.delete(`/ssh-key/${id}`).then(r => r.data)
export const testSshConnection = (data) => API.post('/ssh-test', data).then(r => r.data)
export const getSystems = () => API.get('/systems').then(r => r.data)
export const saveSystem = (data) => API.post('/systems', data).then(r => r.data)
export const deleteSystem = (id) => API.delete(`/systems/${id}`).then(r => r.data)
export const reorderSystems = (updates) => API.post('/systems/reorder', { updates }).then(r => r.data)

// Streaming helper — accepts an AbortSignal so the SSE reader can be
// cancelled when the user switches chats. The backend AI task continues
// independently and saves the response to DB regardless.
export const streamMessage = (chatId, content, model, signal, attachmentIds = []) => {
  const token = localStorage.getItem('auth_token')
  return fetch(apiUrl(`/api/chats/${chatId}/messages`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      content,
      model,
      attachment_ids: attachmentIds.length > 0 ? attachmentIds : undefined,
    }),
    signal,
  })
}

// Attachments
export const uploadAttachment = async (chatId, file) => {
  const token = localStorage.getItem('auth_token')
  const form = new FormData()
  form.append('file', file)
  form.append('chat_id', String(chatId))
  const res = await fetch(apiUrl('/api/attachments'), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()
}

export const deleteAttachment = (id) => API.delete(`/api/attachments/${id}`).then(r => r.data)
export const getAttachmentUrl = (id) => apiUrl(`/api/attachments/${id}/data`)

// Backup
export const previewBackup = (file, password) => {
  const token = localStorage.getItem('auth_token')
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  return fetch(apiUrl('/api/backup/import/preview'), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail || 'Preview failed'))))
}

export const importBackup = (file, password) => {
  const token = localStorage.getItem('auth_token')
  const form = new FormData()
  form.append('file', file)
  if (password) form.append('password', password)
  return fetch(apiUrl('/api/backup/import'), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail || 'Import failed'))))
}

export const exportBackup = async (includes, password) => {
  const token = localStorage.getItem('auth_token')
  const res = await fetch(apiUrl('/api/backup/export'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ includes, password: password || null }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Export failed')
  }
  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : 'backup.aib'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = filename
  document.body.appendChild(a); a.click()
  document.body.removeChild(a); URL.revokeObjectURL(url)
  return filename
}
