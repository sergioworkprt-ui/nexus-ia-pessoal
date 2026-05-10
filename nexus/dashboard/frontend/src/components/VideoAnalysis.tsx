import React, { useState } from 'react'
import { api } from '../api'

const MODES = ['full','summary','concepts','study','truth'] as const
const LABELS: Record<string, string> = { full:'Completo', summary:'Resumo', concepts:'Conceitos', study:'Plano Estudo', truth:'Verificar' }

export default function VideoAnalysis() {
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<string>('full')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<Record<string, string> | null>(null)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('summary')

  const analyze = async () => {
    if (!url.trim()) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await api.videoAnalyze(url, mode) as Record<string, string>
      if (r.error) { setError(r.error + (r.tip ? `\n${r.tip}` : '')) }
      else { setResult(r); setActiveTab(Object.keys(r).find(k => !['video_id','transcript_chars'].includes(k)) ?? 'summary') }
    } catch (e) { setError(String(e)) }
    finally { setLoading(false) }
  }

  const resultTabs = result ? Object.keys(result).filter(k => !['video_id','transcript_chars'].includes(k)) : []

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <div className="space-y-2">
        <div className="flex gap-2">
          <input className="flex-1 bg-nexus-panel border border-nexus-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-nexus-accent"
            placeholder="URL do YouTube…" value={url} onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && analyze()} />
          <button onClick={analyze} disabled={loading || !url.trim()}
            className="px-4 py-2 bg-nexus-accent rounded-lg text-sm font-semibold hover:bg-blue-500 disabled:opacity-40">
            {loading ? <span className="animate-spin">⟳</span> : '▶ Analisar'}
          </button>
        </div>
        <div className="flex gap-1.5">
          {MODES.map(m => (
            <button key={m} onClick={() => setMode(m)}
              className={`px-2.5 py-1 rounded text-xs ${ mode === m ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400'}`}>
              {LABELS[m]}
            </button>
          ))}
        </div>
        {loading && (
          <div className="w-full bg-nexus-border rounded-full h-1">
            <div className="h-1 bg-nexus-accent rounded-full animate-pulse w-3/4" />
          </div>
        )}
      </div>
      {error && <div className="bg-nexus-danger/10 border border-nexus-danger/30 rounded-lg p-3 text-sm text-nexus-danger whitespace-pre-wrap">{error}</div>}
      {result && (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex gap-1.5 mb-3 flex-wrap">
            {resultTabs.map(t => (
              <button key={t} onClick={() => setActiveTab(t)}
                className={`px-2.5 py-1 rounded text-xs ${ activeTab === t ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400'}`}>
                {LABELS[t] ?? t}
              </button>
            ))}
            <span className="text-xs text-gray-500 ml-auto self-center">
              {result.video_id} · {result.transcript_chars} chars
            </span>
          </div>
          <div className="flex-1 overflow-y-auto bg-nexus-panel border border-nexus-border rounded-lg p-4">
            <p className="text-sm text-gray-200 whitespace-pre-wrap">{result[activeTab]}</p>
          </div>
        </div>
      )}
    </div>
  )
}
