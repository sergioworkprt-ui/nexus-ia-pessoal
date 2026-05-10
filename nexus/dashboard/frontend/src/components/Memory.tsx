import React, { useEffect, useState } from 'react'
import { api } from '../api'

interface Entry { role: string; content: string; ts?: string }

export default function Memory() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [n, setN] = useState(50)

  const load = async () => {
    try {
      const r = await api.memory(n) as { entries: Entry[] }
      setEntries(r.entries)
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [n])

  const clear = async () => {
    if (!confirm('Limpar toda a memória?')) return
    await api.clearMemory()
    setEntries([])
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-400">{entries.length} entradas</span>
        <select className="bg-nexus-panel border border-nexus-border rounded px-2 py-1 text-sm"
          value={n} onChange={e => setN(Number(e.target.value))}>
          {[20, 50, 100, 200].map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <button onClick={load} className="px-3 py-1 bg-nexus-border rounded text-sm hover:bg-nexus-accent">↻</button>
        <button onClick={clear} className="px-3 py-1 bg-nexus-danger/20 text-nexus-danger rounded text-sm hover:bg-nexus-danger/40 ml-auto">Limpar</button>
      </div>
      <div className="flex-1 overflow-y-auto space-y-2">
        {entries.length === 0 && <p className="text-gray-500 text-sm text-center mt-12">Memória vazia.</p>}
        {entries.map((e, i) => (
          <div key={i} className={`flex gap-2 ${e.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
              e.role === 'user' ? 'bg-nexus-accent/20 text-blue-200' : 'bg-nexus-panel border border-nexus-border text-gray-300'
            }`}>
              <span className="text-xs text-gray-500 block mb-1">{e.role}</span>
              {String(e.content)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
