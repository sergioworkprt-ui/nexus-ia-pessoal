import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Security() {
  const [pin, setPin] = useState('')
  const [msg, setMsg] = useState('')
  const [audit, setAudit] = useState<string[]>([])
  const [status, setStatus] = useState<Record<string, unknown>>({})

  useEffect(() => {
    api.securityStatus().then(s => setStatus(s as Record<string, unknown>)).catch(() => {})
    api.auditLog(30).then(r => setAudit((r as { lines: string[] }).lines)).catch(() => {})
  }, [])

  const verify = async () => {
    try {
      const r = await api.verifyPin(pin) as { ok: boolean; token?: string }
      if (r.ok) {
        if (r.token) localStorage.setItem('nexus_token', r.token)
        setMsg('✓ PIN correto. Token guardado.')
      } else {
        setMsg('✗ PIN incorreto.')
      }
    } catch (e) {
      setMsg(`Erro: ${e instanceof Error ? e.message : String(e)}`)
    }
    setPin('')
  }

  return (
    <div className="p-6 space-y-6 max-w-lg">
      <div>
        <h2 className="text-nexus-accent font-semibold mb-3">PIN / Token</h2>
        <div className="flex gap-2">
          <input type="password" inputMode="numeric" maxLength={8}
            className="flex-1 bg-nexus-panel border border-nexus-border rounded px-3 py-2 text-sm tracking-widest"
            placeholder="PIN (4+ dígitos)" value={pin} onChange={e => setPin(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && verify()} />
          <button onClick={verify} className="px-4 py-2 bg-nexus-accent rounded text-sm">Verificar</button>
        </div>
        {msg && <p className={`mt-2 text-sm ${msg.startsWith('✓') ? 'text-nexus-success' : 'text-nexus-danger'}`}>{msg}</p>}
      </div>

      <div>
        <h3 className="text-sm text-gray-400 mb-2">Estado</h3>
        <div className="bg-nexus-panel border border-nexus-border rounded p-3 text-xs space-y-1">
          {Object.entries(status).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-gray-400">{k}</span>
              <span className={String(v) === 'true' ? 'text-nexus-success' : 'text-gray-300'}>{String(v)}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm text-gray-400 mb-2">Audit Log (últimas 30)</h3>
        <div className="bg-nexus-panel border border-nexus-border rounded p-3 text-xs font-mono max-h-48 overflow-y-auto space-y-0.5">
          {audit.length === 0 && <span className="text-gray-600">Sem entradas.</span>}
          {audit.map((l, i) => <div key={i} className="text-gray-400">{l}</div>)}
        </div>
      </div>
    </div>
  )
}
