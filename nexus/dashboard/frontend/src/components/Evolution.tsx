import React, { useEffect, useState } from 'react'
import type { Proposal } from '../types'
import { api } from '../api'

const STATUS_COLOR: Record<string, string> = {
  waiting_approval: 'text-nexus-accent', approved: 'text-nexus-warning',
  applied: 'text-nexus-success', rejected: 'text-nexus-danger',
}

export default function Evolution() {
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [desc, setDesc] = useState('')
  const [file, setFile] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    try {
      const r = await api.evolutionList() as { proposals: Proposal[] }
      setProposals(r.proposals)
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [])

  const propose = async () => {
    if (!desc.trim()) return
    setLoading(true)
    try {
      await api.evolutionPropose(desc, file || undefined)
      setDesc('')
      setFile('')
      await load()
    } finally { setLoading(false) }
  }

  const action = async (fn: () => Promise<unknown>) => { await fn(); await load() }

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4 space-y-2">
        <h3 className="text-sm font-semibold text-nexus-accent">Propor Melhoria</h3>
        <textarea className="w-full bg-nexus-bg border border-nexus-border rounded px-3 py-2 text-sm resize-none h-20 focus:outline-none focus:border-nexus-accent"
          placeholder="Descreve a melhoria que queres propor…" value={desc} onChange={e => setDesc(e.target.value)} />
        <div className="flex gap-2">
          <input className="flex-1 bg-nexus-bg border border-nexus-border rounded px-3 py-2 text-xs"
            placeholder="Ficheiro alvo (opcional, ex: modules/trading/trading.py)" value={file} onChange={e => setFile(e.target.value)} />
          <button onClick={propose} disabled={loading || !desc.trim()}
            className="px-4 py-2 bg-nexus-accent rounded text-sm hover:bg-blue-500 disabled:opacity-40">
            {loading ? '…' : 'Propor'}
          </button>
        </div>
        <p className="text-xs text-gray-500">⚠️ Nenhuma alteração é aplicada sem aprovação explícita.</p>
      </div>
      <div className="flex-1 overflow-y-auto space-y-3">
        {proposals.length === 0 && <p className="text-gray-500 text-sm text-center mt-8">Sem propostas.</p>}
        {proposals.map(p => (
          <div key={p.id} className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div>
                <span className={`text-xs font-semibold uppercase ${STATUS_COLOR[p.status] ?? 'text-gray-400'}`}>{p.status}</span>
                <span className="text-xs text-gray-500 ml-2">{p.id}</span>
              </div>
              <span className="text-xs text-gray-500">{p.created_at.slice(0, 16)}</span>
            </div>
            <p className="text-sm mb-2">{p.description}</p>
            {p.target_file && <p className="text-xs text-gray-500 mb-2">📄 {p.target_file}</p>}
            {p.analysis && (
              <div className="text-xs bg-nexus-bg rounded p-2 space-y-1 mb-2">
                <p><span className="text-gray-400">Resumo: </span>{p.analysis.summary}</p>
                <p><span className="text-nexus-warning">Riscos: </span>{p.analysis.risks}</p>
              </div>
            )}
            <div className="flex gap-2">
              {p.status === 'waiting_approval' && (
                <button onClick={() => action(() => api.evolutionApprove(p.id))}
                  className="px-3 py-1 bg-nexus-success/20 text-nexus-success rounded text-xs hover:bg-nexus-success/40">✓ Aprovar</button>
              )}
              {p.status === 'approved' && (
                <button onClick={() => action(() => api.evolutionApply(p.id))}
                  className="px-3 py-1 bg-nexus-warning/20 text-nexus-warning rounded text-xs hover:bg-nexus-warning/40">▶ Aplicar</button>
              )}
              {p.status === 'waiting_approval' && (
                <button onClick={() => action(() => api.evolutionReject(p.id))}
                  className="px-3 py-1 bg-nexus-danger/20 text-nexus-danger rounded text-xs hover:bg-nexus-danger/40">✕ Rejeitar</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
