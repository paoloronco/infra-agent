import React, { useState, useEffect } from 'react'
import { Sun, Moon, Shield, Users, Key, Lock, Unlock, UserPlus, UserMinus, RefreshCw, AlertCircle, CheckCircle } from 'lucide-react'
import { useApp } from '../context/AppContext'
import toast from 'react-hot-toast'
import { apiUrl } from '../api'

function authHeaders(extra = {}) {
  const token = localStorage.getItem('auth_token')
  return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra }
}

async function apiFetch(url, opts = {}) {
  const target = url.startsWith('http') ? url : apiUrl(url)
  const res = await fetch(target, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } })
  return res
}

export default function Settings() {
  const { theme, toggleTheme } = useApp()
  const [authConfig, setAuthConfig] = useState({ enabled: false })
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [showUserForm, setShowUserForm] = useState(false)
  const [newUser, setNewUser] = useState({ username: '', password: '', is_admin: false })
  const [pwForm, setPwForm] = useState({ old: '', new1: '', new2: '' })
  const [showPwForm, setShowPwForm] = useState(false)

  const themes = [
    { id: 'light', label: 'Light', icon: Sun },
    { id: 'dark',  label: 'Dark',  icon: Moon },
  ]

  const fetchAuthConfig = async () => {
    try {
      const res = await fetch(apiUrl('/api/auth/config'))
      const data = await res.json()
      setAuthConfig(data)
      if (data.enabled) fetchUsers()
    } catch { }
  }

  const fetchUsers = async () => {
    try {
      const res = await apiFetch('/api/auth/users')
      if (res.ok) setUsers(await res.json())
    } catch { }
  }

  const toggleAuth = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/auth/config', {
        method: 'PUT',
        body: JSON.stringify({ enabled: !authConfig.enabled }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setAuthConfig(data)
      toast.success(data.message)
      if (data.enabled) fetchUsers()
    } catch (e) {
      toast.error(`Failed to update authentication: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const createUser = async () => {
    if (!newUser.username || !newUser.password) { toast.error('Username and password are required'); return }
    setLoading(true)
    try {
      const res = await apiFetch('/api/auth/users', { method: 'POST', body: JSON.stringify(newUser) })
      const data = await res.json()
      if (res.ok) {
        toast.success(data.message)
        setNewUser({ username: '', password: '', is_admin: false })
        setShowUserForm(false)
        fetchUsers()
      } else {
        toast.error(data.detail || 'Failed to create user')
      }
    } catch { toast.error('Failed to create user') } finally { setLoading(false) }
  }

  const deleteUser = async (username) => {
    if (!confirm(`Delete user "${username}"?`)) return
    setLoading(true)
    try {
      const res = await apiFetch(`/api/auth/users/${username}`, { method: 'DELETE' })
      const data = await res.json()
      if (res.ok) { toast.success(data.message); fetchUsers() }
      else toast.error(data.detail || 'Failed to delete user')
    } catch { toast.error('Failed to delete user') } finally { setLoading(false) }
  }

  const resetPassword = async (username) => {
    setLoading(true)
    try {
      const res = await apiFetch(`/api/auth/reset-password/${username}`, { method: 'POST' })
      const data = await res.json()
      if (res.ok) toast.success(`Password reset to: ${data.new_password}`)
      else toast.error(data.detail || 'Failed to reset password')
    } catch { toast.error('Failed to reset password') } finally { setLoading(false) }
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    if (pwForm.new1 !== pwForm.new2) { toast.error('New passwords do not match'); return }
    if (pwForm.new1.length < 6) { toast.error('New password must be at least 6 characters'); return }
    setLoading(true)
    try {
      const res = await apiFetch('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: pwForm.old, new_password: pwForm.new1 }),
      })
      const data = await res.json()
      if (res.ok) {
        toast.success('Password changed — please log in again')
        localStorage.removeItem('auth_token')
        setTimeout(() => window.dispatchEvent(new Event('auth:logout')), 1000)
      } else {
        toast.error(data.detail || 'Failed to change password')
      }
    } catch { toast.error('Failed to change password') } finally { setLoading(false) }
  }

  useEffect(() => { fetchAuthConfig() }, [])

  return (
    <div className="mx-auto max-w-2xl p-4 sm:p-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">Settings</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-8">App preferences</p>

      {/* Theme */}
      <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 mb-4">
        <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Appearance</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {themes.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { if (theme !== id) toggleTheme() }}
              className={`flex w-full items-center gap-2 px-4 py-3 rounded-xl border-2 text-sm font-medium transition-all
                ${theme === id
                  ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400'
                  : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300'}`}>
              <Icon size={16} /> {label}
            </button>
          ))}
        </div>
      </section>

      {/* Authentication */}
      <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 mb-4">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Shield size={18} /> Authentication
          </h2>
          <button onClick={toggleAuth} disabled={loading}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
              ${authConfig.enabled
                ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-300'
                : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300'}
              ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}>
            {authConfig.enabled ? <Lock size={16} /> : <Unlock size={16} />}
            {authConfig.enabled ? 'Enabled' : 'Disabled'}
          </button>
        </div>

        {authConfig.enabled ? (
          <div className="space-y-4">
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-3 flex items-center gap-2 text-sm text-green-700 dark:text-green-300">
              <CheckCircle size={16} /> Authentication is active — login required to access the app
            </div>

            {/* Change password */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                  <Key size={16} /> Change Password
                </h3>
                <button onClick={() => setShowPwForm(f => !f)}
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
                  {showPwForm ? 'Cancel' : 'Change'}
                </button>
              </div>
              {showPwForm && (
                <form onSubmit={handleChangePassword} className="bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg p-4 space-y-3">
                  <input type="password" placeholder="Current password" required
                    value={pwForm.old} onChange={e => setPwForm(f => ({ ...f, old: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm" />
                  <input type="password" placeholder="New password (min 6 chars)" required
                    value={pwForm.new1} onChange={e => setPwForm(f => ({ ...f, new1: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm" />
                  <input type="password" placeholder="Confirm new password" required
                    value={pwForm.new2} onChange={e => setPwForm(f => ({ ...f, new2: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm" />
                  <button type="submit" disabled={loading}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg disabled:opacity-50">
                    {loading ? 'Saving…' : 'Save new password'}
                  </button>
                </form>
              )}
            </div>

            {/* User management */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                  <Users size={16} /> User Management
                </h3>
                <button onClick={() => setShowUserForm(!showUserForm)}
                  className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors">
                  <UserPlus size={14} /> Add User
                </button>
              </div>

              {showUserForm && (
                <div className="bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-3 space-y-3">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <input type="text" placeholder="Username" value={newUser.username}
                      onChange={e => setNewUser({ ...newUser, username: e.target.value })}
                      className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm" />
                    <input type="password" placeholder="Password" value={newUser.password}
                      onChange={e => setNewUser({ ...newUser, password: e.target.value })}
                      className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm" />
                  </div>
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                    <input type="checkbox" checked={newUser.is_admin}
                      onChange={e => setNewUser({ ...newUser, is_admin: e.target.checked })}
                      className="rounded border-gray-300 text-indigo-600" />
                    Administrator privileges
                  </label>
                  <div className="flex gap-2">
                    <button onClick={createUser} disabled={loading}
                      className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg disabled:opacity-50">
                      Create User
                    </button>
                    <button onClick={() => { setShowUserForm(false); setNewUser({ username: '', password: '', is_admin: false }) }}
                      className="px-3 py-1.5 bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-300 text-sm rounded-lg">
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {users.map(user => (
                  <div key={user.username} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg">
                    <div className="flex items-center gap-3">
                      {user.is_admin ? <Shield size={16} className="text-indigo-500" /> : <Users size={16} className="text-gray-500" />}
                      <span className="font-medium text-gray-900 dark:text-white text-sm">{user.username}</span>
                      <div className="flex gap-1">
                        {user.is_admin && <span className="px-1.5 py-0.5 text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded">Admin</span>}
                        {user.is_locked && <span className="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded">Locked</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => resetPassword(user.username)} disabled={loading} title="Reset password to username+123"
                        className="p-1.5 text-gray-500 hover:text-amber-600 dark:hover:text-amber-400 transition-colors">
                        <RefreshCw size={14} />
                      </button>
                      {user.username !== 'admin' && (
                        <button onClick={() => deleteUser(user.username)} disabled={loading} title="Delete user"
                          className="p-1.5 text-gray-500 hover:text-red-600 dark:hover:text-red-400 transition-colors">
                          <UserMinus size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-3 flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
            <AlertCircle size={16} />
            Authentication is disabled — anyone can access the application
          </div>
        )}
      </section>

      {/* About */}
      <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        <h2 className="font-semibold text-gray-900 dark:text-white mb-3">About</h2>
        <div className="text-sm text-gray-500 dark:text-gray-400 space-y-1">
          <p>AI Agent SSH &amp; Troubleshooting</p>
          <p>Version 2.0.0 · LangChain · FastAPI · React · SQLite</p>
        </div>
      </section>
    </div>
  )
}
