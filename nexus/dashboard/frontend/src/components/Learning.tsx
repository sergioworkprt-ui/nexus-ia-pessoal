import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Learning() {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [providers, setProviders] = useState<string[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [synthesis, setSynthesis] = useState('')
  const [mode, setMode] = useState<'multi' | 'synthesize'>('synthesize')

  useEffect(() => {
    api.learningProviders().then(r => setProviders((r as { providers: string[] }).providers)).catch(() => {})
  }, [])

  const query = async () => {
    if (!question.trim()) return
    setLoading(true)
    setAnswers({})
    setSynthesis('')
    try {
      if (mode === 'synthesize') {
        const r = await api.learningSynthesize(question) as { answers: Record<string, string>; synthesis: string }
        setAnswers(r.answers)
        setSynthesis(r.synthesis)
      } else {
        const r = await api.learningMulti(question) as { answers: Record<string, string> }
        setAnswers(r.answers)
      }
    } catch (e) {
      setAnswers({ error: String(e) })
    } finally { setLoading(false) }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <div className="space-y-2">
        <div className="flex gap-2">
          <button onClick={() => setMode('multi')} className={`px-3 py-1.5 rounded text-sm ${ mode === 'multi' ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400'}`}>Multi-IA</button>
          <button onClick={() => setMode('synthesize')} className={`px-3 py-1.5 rounded text-sm ${ mode === 'synthesize' ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400'}`}>Síntese</button>
          <span className="text-xs text-gray-500 ml-auto self-center">Providers: {providers.join(', ') || 'nenhum configurado'}</span>
        </div>
        <div className="flex gap-2">
          <textarea
            className="flex-1 bg-nexus-panel border border-nexus-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-nexus-accent resize-none h-20"
            placeholder="Pergunta para as IAs…" value={question} onChange={e => setQuestion(e.target.value)}
          />
          <button onClick={query} disabled={loading || !question.trim()}
            className="px-4 rounded-lg bg-nexus-accent hover:bg-blue-500 disabled:opacity-40 text-sm font-semibold">
            {loading ? '…' : '▶'}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto space-y-3">
        {synthesis && (
          <div className="bg-nexus-panel border border-nexus-accent/30 rounded-lg p-4">
            <p className="text-xs text-nexus-accent font-semibold mb-2">✨ Síntese</p>
            <p className="text-sm text-gray-200 whitespace-pre-wrap">{synthesis}</p>
          </div>
        )}
        {Object.entries(answers).map(([prov, ans]) => (
          <div key={prov} className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
            <p className="text-xs text-nexus-warning font-semibold mb-2 uppercase">{prov}</p>
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{ans}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
