import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'

const SERVICES = ['api', 'core', 'dashboard', 'audit']

export default function Logs() {
  const [service, setService] = useState('core')
  const [lines, setLines] = useState<string[]>([])
  const [n, setN] = useState(150)
  const [auto, setAuto] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    try {
      const r = await api.logs(service, n) as { lines: string[] }
      setLines(r.lines)
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [service, n])
  useEffect(() => { if (!auto) return; const t = setInterval(load, 3000); return () => clearInterval(t) }, [auto, service, n])
  useEffect(() => { if (auto) bottomRef.current?.scrollIntoView() }, [lines, auto])

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 p-3 border-b border-nexus-border shrink-0">
        {SERVICES.map(s => (
          <button key={s} onClick={() => setService(s)}
            className={`px-3 py-1 rounded text-sm ${ service === s ? 'bg-nexus-accent text-white' : 'bg-nexus-border text-gray-400'}`}>
            {s}
          </button>
        ))}
        <select className="bg-nexus-panel border border-nexus-border rounded px-2 py-1 text-sm ml-auto" value={n} onChange={e => setN(Number(e.target.value))}>
          {[50,100,150,300].map(v => <option key={v} value={v}>{v} linhas</option>)}
        </select>
        <button onClick={() => setAuto(v => !v)}
          className={`px-3 py-1 rounded text-sm ${ auto ? 'bg-nexus-success/20 text-nexus-success' : 'bg-nexus-border text-gray-400'}`}>
          {auto ? '⏸ Auto' : '▶ Auto'}
        </button>
        <button onClick={load} className="px-3 py-1 bg-nexus-border rounded text-sm hover:bg-nexus-accent">↻</button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs text-gray-400 space-y-0.5">
        {lines.length === 0 && <span className="text-gray-600">Sem logs.</span>}
        {lines.map((l, i) => (
          <div key={i} className={`
            ${l.includes('ERROR') || l.includes('ERRO') ? 'text-nexus-danger' : ''}
            ${l.includes('WARN') ? 'text-nexus-warning' : ''}
            ${l.includes('INFO') ? 'text-gray-300' : ''}
          `}>{l}</div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
