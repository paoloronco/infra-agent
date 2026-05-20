import React, { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  MessageSquare, Brain, BarChart2, Clock, Terminal,
  Shield, Settings, ChevronLeft, ChevronRight, Sun, Moon, Plus, FileText, X, Archive
} from 'lucide-react'
import { useApp } from '../context/AppContext'
import { createChat } from '../api'
import toast from 'react-hot-toast'

const NAV = [
  { to: '/',         icon: MessageSquare, label: 'Chat' },
  { to: '/models',   icon: Brain,         label: 'Models' },
  { to: '/usage',    icon: BarChart2,      label: 'Usage' },
  { to: '/logs',     icon: FileText,        label: 'Logs' },
  { to: '/cron',     icon: Clock,         label: 'Cron Jobs' },
  { to: '/ssh',      icon: Terminal,      label: 'SSH Manager' },
  { to: '/perms',    icon: Shield,        label: 'AI Safety' },
  { to: '/backup',   icon: Archive,       label: 'Backup' },
  { to: '/settings', icon: Settings,      label: 'Settings' },
]

export default function Sidebar({ mobileOpen = false, onMobileClose = () => {} }) {
  const [collapsed, setCollapsed] = useState(false)
  const { theme, toggleTheme, setActiveChatId } = useApp()
  const navigate = useNavigate()
  const showLabels = !collapsed || mobileOpen

  const handleNewChat = async () => {
    try {
      const chat = await createChat({ title: 'New Chat' })
      setActiveChatId(chat.id)
      navigate('/')
      onMobileClose()
    } catch {
      toast.error('Failed to create chat')
    }
  }

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-gray-950/60 transition-opacity md:hidden ${
          mobileOpen ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onMobileClose}
        aria-hidden={!mobileOpen}
      />
      <aside className={`
        fixed inset-y-0 left-0 z-[60] flex h-screen w-64 shrink-0 flex-col border-r border-gray-700 bg-gray-900 transition-transform duration-300 md:static md:z-auto md:translate-x-0 dark:bg-gray-950
        ${mobileOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'}
        ${collapsed ? 'md:w-16' : 'md:w-64'}
      `}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-4 border-b border-gray-700">
        {showLabels && (
          <span className="text-white font-semibold text-sm truncate">AI Agent</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onMobileClose}
            className="rounded p-1 text-gray-400 hover:text-white md:hidden"
            aria-label="Close navigation menu"
          >
            <X size={16} />
          </button>
          <button onClick={() => setCollapsed(c => !c)}
            className="hidden text-gray-400 hover:text-white p-1 rounded md:inline-flex">
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>
      </div>

      {/* New Chat */}
      <div className="px-2 py-2">
        <button onClick={handleNewChat}
          className={`
            flex items-center gap-2 w-full rounded-lg px-3 py-2
            bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium
            transition-colors
            ${showLabels ? '' : 'justify-center'}
          `}>
          <Plus size={16} />
          {showLabels && <span>New Chat</span>}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-2 space-y-1 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} end={to === '/'}
            onClick={onMobileClose}
            className={({ isActive }) => `
              flex items-center gap-3 px-3 py-2 rounded-lg text-sm
              transition-colors group
              ${isActive
                ? 'bg-indigo-600 text-white'
                : 'text-gray-400 hover:bg-gray-800 hover:text-white'}
              ${showLabels ? '' : 'justify-center'}
            `}>
            <Icon size={18} className="shrink-0" />
            {showLabels && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-2 py-3 border-t border-gray-700">
        <button onClick={toggleTheme}
          className={`
            flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm
            text-gray-400 hover:bg-gray-800 hover:text-white transition-colors
            ${showLabels ? '' : 'justify-center'}
          `}>
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          {showLabels && <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>}
        </button>
      </div>
      </aside>
    </>
  )
}
