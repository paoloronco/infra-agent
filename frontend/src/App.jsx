import React, { useState, useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { Menu, X } from 'lucide-react'
import { AppProvider } from './context/AppContext'
import Sidebar from './layout/Sidebar'
import Login from './pages/Login'
import Chat from './pages/Chat'
import Models from './pages/Models'
import Usage from './pages/Usage'
import Logs from './pages/Logs'
import CronJobs from './pages/CronJobs'
import SshManager from './pages/SshManager'
import Permissions from './pages/Permissions'
import Settings from './pages/Settings'
import { apiUrl } from './api'
import Backup from './pages/Backup'

function AppShell() {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  return (
    <AppProvider>
      <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
        <Sidebar mobileOpen={mobileSidebarOpen} onMobileClose={() => setMobileSidebarOpen(false)} />
        <main className="relative flex-1 min-w-0 overflow-y-auto pt-14 md:pt-0">
          <button type="button" onClick={() => setMobileSidebarOpen(o => !o)}
            className="fixed left-3 top-3 z-40 inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white p-2 text-gray-700 shadow-sm transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700 md:hidden"
            aria-label="Toggle menu">
            {mobileSidebarOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <Routes>
            <Route path="/"         element={<Chat />} />
            <Route path="/models"   element={<Models />} />
            <Route path="/usage"    element={<Usage />} />
            <Route path="/logs"     element={<Logs />} />
            <Route path="/cron"     element={<CronJobs />} />
            <Route path="/ssh"      element={<SshManager />} />
            <Route path="/perms"    element={<Permissions />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/backup"   element={<Backup />} />
          </Routes>
        </main>
      </div>
    </AppProvider>
  )
}

export default function App() {
  const [authRequired, setAuthRequired] = useState(false)
  const [authenticated, setAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)

  const checkAuth = async () => {
    try {
      const res = await fetch(apiUrl('/api/auth/config'))
      const data = await res.json()
      if (!data.enabled) {
        setAuthRequired(false)
        setAuthenticated(true)
      } else {
        setAuthRequired(true)
        setAuthenticated(!!localStorage.getItem('auth_token'))
      }
    } catch {
      setAuthenticated(true) // backend unreachable — let through
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    checkAuth()
    const onLogout = () => { setAuthenticated(false) }
    window.addEventListener('auth:logout', onLogout)
    return () => window.removeEventListener('auth:logout', onLogout)
  }, [])

  if (checking) return null

  if (authRequired && !authenticated) {
    return (
      <>
        <Login onLogin={() => setAuthenticated(true)} />
        <Toaster position="bottom-right" />
      </>
    )
  }

  return (
    <>
      <AppShell />
      <Toaster position="bottom-right"
        toastOptions={{
          style: { background: '#1f2937', color: '#f9fafb', fontSize: '14px' },
          success: { iconTheme: { primary: '#6366f1', secondary: '#fff' } },
        }} />
    </>
  )
}
