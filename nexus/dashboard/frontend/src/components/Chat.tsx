import React, { useCallback, useEffect, useRef, useState } from 'react'

interface Message {
  role: 'user' | 'nexus'
  content: string
  ts: number
}

interface Props {
  onStateChange: (state: 'idle' | 'thinking' | 'speaking') => void
}

export default function Chat({ onStateChange }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const token = localStorage.getItem('nexus_token') ?? ''

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text, ts: Date.now() }])
    setLoading(true)
    onStateChange('thinking')
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: text }),
      })
      const data = await r.json()
      onStateChange('speaking')
      setMessages(prev => [...prev, { role: 'nexus', content: data.response, ts: Date.now() }])
      setTimeout(() => onStateChange('idle'), 3000)
    } catch {
      setMessages(prev => [...prev, { role: 'nexus', content: 'Erro de comunicação.', ts: Date.now() }])
      onStateChange('idle')
    } finally {
      setLoading(false)
    }
  }, [input, loading, onStateChange, token])

  return (
    <div className="flex flex-col h-full bg-nexus-panel border border-nexus-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-nexus-border text-sm font-semibold text-nexus-accent">
        Chat NEXUS
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m) => (
          <div key={m.ts} className={`flex ${ m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] px-3 py-2 rounded-lg text-sm ${
              m.role === 'user'
                ? 'bg-nexus-accent text-white'
                : 'bg-nexus-border text-gray-200'
            }`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-nexus-border px-3 py-2 rounded-lg text-sm text-gray-400 animate-pulse">
              A processar…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="p-3 border-t border-nexus-border flex gap-2">
        <input
          className="flex-1 bg-nexus-bg border border-nexus-border rounded px-3 py-2 text-sm
                     focus:outline-none focus:border-nexus-accent"
          placeholder="Fala comigo, NEXUS..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendMessage()}
        />
        <button
          onClick={sendMessage}
          disabled={loading}
          className="px-4 py-2 bg-nexus-accent rounded text-sm font-semibold
                     hover:bg-blue-500 disabled:opacity-50 transition-colors"
        >
          Enviar
        </button>
      </div>
    </div>
  )
}
