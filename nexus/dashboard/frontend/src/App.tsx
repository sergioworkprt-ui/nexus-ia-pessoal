import React, { useEffect, useRef, useState } from 'react'
import type { AvatarState, Tab } from './types'
import Sidebar from './components/Sidebar'
import Avatar from './components/Avatar'
import Chat from './components/Chat'
import Tasks from './components/Tasks'
import Memory from './components/Memory'
import Settings from './components/Settings'
import Security from './components/Security'
import Finance from './components/Finance'
import Learning from './components/Learning'
import Monitor from './components/Monitor'
import VideoAnalysis from './components/VideoAnalysis'
import Logs from './components/Logs'
import Evolution from './components/Evolution'
import { wsUrl } from './api'

const PANELS: Record<Tab, React.ReactNode> = {} as Record<Tab, React.ReactNode>

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')
  const [avatarState, setAvatarState] = useState<AvatarState>('idle')
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let ws: WebSocket
    let retry: ReturnType<typeof setTimeout>

    function connect() {
      try {
        ws = new WebSocket(wsUrl())
        wsRef.current = ws
        ws.onopen = () => setConnected(true)
        ws.onclose = () => {
          setConnected(false)
          retry = setTimeout(connect, 4000)
        }
        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data)
            if (msg.avatar_state) setAvatarState(msg.avatar_state as AvatarState)
          } catch { /* ignore */ }
        }
      } catch { /* ignore */ }
    }
    connect()
    return () => {
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  const panels: Record<Tab, React.ReactNode> = {
    chat:      <Chat onAvatarState={setAvatarState} ws={wsRef.current} />,
    tasks:     <Tasks />,
    memory:    <Memory />,
    settings:  <Settings />,
    security:  <Security />,
    finance:   <Finance />,
    learning:  <Learning />,
    monitor:   <Monitor />,
    video:     <VideoAnalysis />,
    logs:      <Logs />,
    evolution: <Evolution />,
    about:     <About />,
  }

  return (
    <div className="flex h-screen bg-nexus-bg text-white overflow-hidden">
      <Sidebar active={tab} onChange={setTab} connected={connected} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <header className="flex items-center justify-between px-5 py-3 border-b border-nexus-border shrink-0">
          <div className="flex items-center gap-3">
            <Avatar state={avatarState} size="sm" />
            <span className="font-bold tracking-widest text-nexus-accent uppercase">NEXUS</span>
            <span className="text-xs text-gray-500">v2.0</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full ${connected ? 'bg-nexus-success/20 text-nexus-success' : 'bg-nexus-danger/20 text-nexus-danger'}`}>
              {connected ? 'WS online' : 'WS offline'}
            </span>
          </div>
        </header>
        <main className="flex-1 overflow-hidden">
          {panels[tab]}
        </main>
      </div>
    </div>
  )
}

function About() {
  return (
    <div className="p-8 max-w-lg">
      <h2 className="text-nexus-accent text-lg font-bold mb-4">NEXUS v2.0</h2>
      <ul className="space-y-2 text-sm text-gray-300">
        {[
          'Chat com IA (texto + voz)',
          'Multi-AI learning (OpenAI, Claude, Gemini)',
          'Análise de vídeos YouTube',
          'Verificação de verdade',
          'Trading XTB + IBKR',
          'Evolução controlada do código',
          'Sistema de tarefas com aprovação',
          'Segurança PIN + JWT',
          'Monitor de sistema',
          'Logs em tempo real',
          'PWA installável',
        ].map(f => <li key={f} className="flex gap-2"><span className="text-nexus-success">✓</span>{f}</li>)}
      </ul>
    </div>
  )
}
