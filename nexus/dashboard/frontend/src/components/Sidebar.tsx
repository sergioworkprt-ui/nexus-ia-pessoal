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
    <nav className="flex flex-col w-14 md:w-52 bg-nexus-panel border-r border-nexus-border shrink-0 overflow-y-auto overflow-x-hidden">

      {/* ── NEXUS Logo ───────────────────────────────── */}
      <div className="flex flex-col items-center gap-2 px-2 py-4 border-b border-nexus-border shrink-0">

        {/* Desktop logo — responsive, max 160px, max 20vw */}
        <div
          className="hidden md:flex items-center justify-center rounded-full border-2 border-nexus-accent"
          style={{
            width:      'min(160px, 20vw)',
            height:     'min(160px, 20vw)',
            background: 'rgba(59,130,246,0.07)',
            boxShadow:  '0 0 28px rgba(59,130,246,0.15)',
            flexShrink: 0,
          }}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="1.5"
            style={{ width: '52%', height: '52%' }}
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
          </svg>
        </div>

        {/* Mobile logo — compact 36 px */}
        <div
          className="flex md:hidden items-center justify-center rounded-full border-2 border-nexus-accent"
          style={{
            width:      36,
            height:     36,
            background: 'rgba(59,130,246,0.07)',
            flexShrink: 0,
          }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="1.5"
            style={{ width: '65%', height: '65%' }}>
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
          </svg>
        </div>

        <span className="hidden md:block font-bold text-sm tracking-[0.2em] text-nexus-accent uppercase select-none">
          NEXUS
        </span>

        {/* Connection status */}
        <div className={`flex items-center gap-1.5 text-xs ${connected ? 'text-nexus-success' : 'text-nexus-danger'}`}>
          <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            connected ? 'bg-nexus-success animate-pulse' : 'bg-nexus-danger'
          }`} />
          <span className="hidden md:inline">{connected ? 'Online' : 'Offline'}</span>
        </div>
      </div>

      {/* ── Nav items ────────────────────────────────── */}
      <div className="flex flex-col gap-0.5 py-2 flex-1">
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
            <span className="text-base w-5 text-center shrink-0">{item.icon}</span>
            <span className="hidden md:block truncate">{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
