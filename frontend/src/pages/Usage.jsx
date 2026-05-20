import React, { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { MessageSquare, Zap, Database, TrendingUp } from 'lucide-react'
import { getUsageSummary, getUsageByModel, getUsageDaily } from '../api'

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon size={18} className="text-white" />
        </div>
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function Usage() {
  const [summary, setSummary] = useState(null)
  const [byModel, setByModel] = useState([])
  const [daily, setDaily] = useState([])

  useEffect(() => {
    getUsageSummary().then(setSummary).catch(() => {})
    getUsageByModel().then(setByModel).catch(() => {})
    getUsageDaily(14).then(setDaily).catch(() => {})
  }, [])

  const fmt = n => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-1">Usage</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Token consumption and activity stats</p>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <StatCard icon={MessageSquare} label="Total Chats" value={summary.total_chats} color="bg-indigo-500" />
          <StatCard icon={MessageSquare} label="Total Messages" value={fmt(summary.total_messages)}
            sub={`${summary.recent_messages_7d} last 7 days`} color="bg-blue-500" />
          <StatCard icon={Zap} label="Input Tokens" value={fmt(summary.total_input_tokens)} color="bg-amber-500" />
          <StatCard icon={Database} label="Output Tokens" value={fmt(summary.total_output_tokens)} color="bg-green-500" />
        </div>
      )}

      {/* Daily chart */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 mb-6">
        <h2 className="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
          <TrendingUp size={16} /> Daily Activity (14 days)
        </h2>
        {daily.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-8">No data yet</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af' }}
                tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} />
              <Tooltip contentStyle={{ background: '#1f2937', border: 'none', borderRadius: '8px', fontSize: '12px' }}
                labelStyle={{ color: '#e5e7eb' }} />
              <Bar dataKey="requests" fill="#6366f1" radius={[4, 4, 0, 0]} name="Requests" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* By model */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Usage by Model</h2>
        {byModel.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">No data yet</p>
        ) : (
          <div className="space-y-3">
            {byModel.map(m => (
              <div key={m.model} className="flex items-center gap-4">
                <span className="text-sm text-gray-700 dark:text-gray-300 w-48 truncate">{m.model}</span>
                <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-2">
                  <div className="bg-indigo-500 h-2 rounded-full"
                    style={{ width: `${Math.min(100, (m.requests / Math.max(...byModel.map(x => x.requests))) * 100)}%` }} />
                </div>
                <span className="text-xs text-gray-400 w-20 text-right">{m.requests} req</span>
                <span className="text-xs text-gray-400 w-24 text-right">{fmt(m.input_tokens + m.output_tokens)} tok</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
