import React, { useEffect, useState } from 'react'
import Avatar from './components/Avatar'
import Chat from './components/Chat'
import TradingPanel from './components/TradingPanel'

interface SystemStatus {
  name: string
  version: string
  modules: Record<string, string>
  trading_mode: string
}

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [avatarState, setAvatarState] = useState<'idle' | 'thinking' | 'speaking'>('idle')

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const r = await fetch('/api/status')
        const data = await r.json()
        setStatus(data)
      } catch {}
    }
    fetchStatus()
    const id = setInterval(fetchStatus, 10_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.avatar_state) setAvatarState(msg.avatar_state)
    }
    return () => ws.close()
  }, [])

  return (
    <div className="min-h-screen flex flex-col bg-nexus-bg">
      <header className="flex items-center justify-between px-6 py-4 border-b border-nexus-border">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-nexus-accent animate-pulse" />
          <span className="text-xl font-bold tracking-widest uppercase text-nexus-accent">
            NEXUS
          </span>
          {status && (
            <span className="text-xs text-gray-500 ml-2">v{status.version}</span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {status && (
            <span className={`text-xs px-2 py-1 rounded ${
              status.trading_mode === 'real'
                ? 'bg-nexus-danger/20 text-nexus-danger'
                : 'bg-nexus-success/20 text-nexus-success'
            }`}>
              {status.trading_mode.toUpperCase()}
            </span>
          )}
          <span className="text-xs text-nexus-success">ONLINE</span>
        </div>
      </header>

      <main className="flex flex-1 gap-4 p-4 overflow-hidden">
        <div className="flex flex-col gap-4 w-64 shrink-0">
          <Avatar state={avatarState} />
          {status && (
            <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
              <p className="text-xs text-gray-400 uppercase mb-2">Módulos</p>
              {Object.entries(status.modules).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xs mb-1">
                  <span className="text-gray-300">{k}</span>
                  <span className={v === 'running' ? 'text-nexus-success' : 'text-nexus-danger'}>
                    {v}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 flex flex-col min-w-0">
          <Chat onStateChange={setAvatarState} />
        </div>

        <div className="w-80 shrink-0">
          <TradingPanel />
        </div>
      </main>
    </div>
  )
}
