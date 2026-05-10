import React, { useCallback, useEffect, useRef, useState } from 'react'
import type { AvatarState, Message } from '../types'
import Avatar from './Avatar'
import { api } from '../api'

const MODES = ['normal', 'teacher', 'technical', 'creative', 'detailed', 'quick']
const MODE_PT: Record<string, string> = {
  normal: 'Normal', teacher: 'Professor', technical: 'Técnico',
  creative: 'Criativo', detailed: 'Detalhado', quick: 'Rápido',
}

interface Props {
  onAvatarState: (s: AvatarState) => void
  ws: WebSocket | null
}

export default function Chat({ onAvatarState, ws }: Props) {
  const [msgs, setMsgs] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('normal')
  const [ttsOn, setTtsOn] = useState(false)
  const [listening, setListening] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs])

  const speak = useCallback((text: string) => {
    if (!ttsOn || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'pt-PT'
    window.speechSynthesis.speak(u)
  }, [ttsOn])

  const send = useCallback(async (text?: string) => {
    const msg = (text ?? input).trim()
    if (!msg || loading) return
    setInput('')
    setMsgs(prev => [...prev, { role: 'user', content: msg, ts: Date.now(), mode }])
    setLoading(true)
    onAvatarState('thinking')
    try {
      const r = await api.chat(msg, mode) as { response: string }
      onAvatarState('speaking')
      setMsgs(prev => [...prev, { role: 'nexus', content: r.response, ts: Date.now() }])
      speak(r.response)
      setTimeout(() => onAvatarState('idle'), 3000)
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e)
      setMsgs(prev => [...prev, { role: 'nexus', content: `Erro: ${err}`, ts: Date.now() }])
      onAvatarState('idle')
    } finally {
      setLoading(false)
    }
  }, [input, loading, mode, onAvatarState, speak])

  const toggleMic = useCallback(() => {
    const SR = window.SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: typeof SpeechRecognition }).webkitSpeechRecognition
    if (!SR) return alert('STT não suportado neste browser.')
    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }
    const r = new SR()
    r.lang = 'pt-PT'
    r.continuous = false
    r.interimResults = false
    r.onresult = (e: SpeechRecognitionEvent) => {
      const t = e.results[0][0].transcript
      setListening(false)
      send(t)
    }
    r.onerror = () => setListening(false)
    r.onend = () => setListening(false)
    recognitionRef.current = r
    r.start()
    setListening(true)
  }, [listening, send])

  return (
    <div className="flex h-full">
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Mode selector */}
        <div className="flex gap-1.5 px-3 py-2 border-b border-nexus-border shrink-0 overflow-x-auto">
          {MODES.map(m => (
            <button key={m} onClick={() => setMode(m)}
              className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
                mode === m ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400 hover:text-white'
              }`}>
              {MODE_PT[m]}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setTtsOn(v => !v)}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                ttsOn ? 'bg-nexus-success/20 text-nexus-success' : 'bg-nexus-border text-gray-500'
              }`}>
              🔊
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {msgs.length === 0 && (
            <p className="text-center text-gray-600 text-sm mt-16">Olá! Como posso ajudar?</p>
          )}
          {msgs.map(m => (
            <div key={m.ts} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'} gap-2`}>
              {m.role === 'nexus' && <div className="mt-1 shrink-0"><Avatar state="idle" size="sm" /></div>}
              <div className={`max-w-[78%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-nexus-accent text-white rounded-tr-sm'
                  : 'bg-nexus-panel border border-nexus-border text-gray-200 rounded-tl-sm'
              }`}>
                {m.content}
                {m.mode && m.mode !== 'normal' && m.role === 'user' && (
                  <span className="ml-2 text-xs opacity-60">[{MODE_PT[m.mode]}]</span>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start gap-2">
              <Avatar state="thinking" size="sm" />
              <div className="bg-nexus-panel border border-nexus-border px-4 py-2 rounded-2xl rounded-tl-sm">
                <span className="inline-flex gap-1">
                  {[0,1,2].map(i => <span key={i} className="w-1.5 h-1.5 bg-nexus-accent rounded-full animate-bounce" style={{animationDelay:`${i*0.15}s`}} />)}
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-3 border-t border-nexus-border flex gap-2 shrink-0">
          <button onClick={toggleMic}
            className={`px-3 py-2 rounded-lg transition-colors shrink-0 ${
              listening ? 'bg-nexus-danger text-white animate-pulse' : 'bg-nexus-border text-gray-400 hover:text-white'
            }`}>
            🎤
          </button>
          <input
            className="flex-1 bg-nexus-bg border border-nexus-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-nexus-accent"
            placeholder={listening ? 'A ouvir…' : `Modo ${MODE_PT[mode]} — escreve ou usa o microfone`}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          />
          <button onClick={() => send()} disabled={loading || !input.trim()}
            className="px-4 py-2 bg-nexus-accent rounded-lg text-sm font-semibold hover:bg-blue-500 disabled:opacity-40 transition-colors shrink-0">
            ➤
          </button>
        </div>
      </div>
    </div>
  )
}
