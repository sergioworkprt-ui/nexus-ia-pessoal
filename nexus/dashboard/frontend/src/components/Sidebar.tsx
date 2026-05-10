import React from 'react'
import type { Tab } from '../types'

const ITEMS: { id: Tab; icon: string; label: string }[] = [
  { id: 'chat',      icon: '💬', label: 'Chat' },
  { id: 'tasks',     icon: '✅', label: 'Tarefas' },
  { id: 'memory',    icon: '🧠', label: 'Memória' },
  { id: 'finance',   icon: '📈', label: 'Finanças' },
  { id: 'learning',  icon: '📚', label: 'Aprender' },
  { id: 'video',     icon: '🎬', label: 'Vídeos' },
  { id: 'evolution', icon: '🔬', label: 'Evolução' },
  { id: 'monitor',   icon: '📊', label: 'Monitor' },
  { id: 'logs',      icon: '📋', label: 'Logs' },
  { id: 'security',  icon: '🔒', label: 'Segurança' },
  { id: 'settings',  icon: '⚙️', label: 'Definições' },
  { id: 'about',     icon: 'ℹ️', label: 'Sobre' },
]

interface Props {
  active: Tab
  onChange: (t: Tab) => void
  connected: boolean
}

export default function Sidebar({ active, onChange, connected }: Props) {
  return (
    <nav className="flex flex-col w-14 md:w-48 bg-nexus-panel border-r border-nexus-border shrink-0 py-3 gap-0.5 overflow-y-auto">
      <div className="hidden md:flex items-center gap-2 px-3 pb-3 border-b border-nexus-border mb-1">
        <div className={`w-2 h-2 rounded-full ${connected ? 'bg-nexus-success' : 'bg-nexus-danger'} animate-pulse`} />
        <span className="text-xs text-gray-400">{connected ? 'Online' : 'Offline'}</span>
      </div>
      {ITEMS.map(item => (
        <button
          key={item.id}
          onClick={() => onChange(item.id)}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-lg mx-1 text-sm transition-colors ${
            active === item.id
              ? 'bg-nexus-accent/20 text-nexus-accent'
              : 'text-gray-400 hover:bg-nexus-border hover:text-white'
          }`}
        >
          <span className="text-base w-5 text-center">{item.icon}</span>
          <span className="hidden md:block truncate">{item.label}</span>
        </button>
      ))}
    </nav>
  )
}
