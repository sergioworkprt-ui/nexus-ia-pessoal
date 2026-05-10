import React, { useEffect, useState } from 'react'
import { api } from '../api'

function Bar({ value, color = '#3b82f6' }: { value: number; color?: string }) {
  return (
    <div className="w-full bg-nexus-border rounded-full h-1.5 mt-1">
      <div className="h-1.5 rounded-full transition-all" style={{ width: `${value}%`, background: color }} />
    </div>
  )
}

export default function Monitor() {
  const [metrics, setMetrics] = useState<Record<string, number | string>>({})
  const [status, setStatus] = useState<Record<string, unknown>>({})
  const [err, setErr] = useState('')

  const load = async () => {
    try {
      const [m, s] = await Promise.all([api.metrics(), api.status()])
      setMetrics(m as Record<string, number | string>)
      setStatus(((s as { modules: Record<string, unknown> }).modules) ?? {})
      setErr('')
    } catch (e) { setErr(String(e)) }
  }

  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t) }, [])

  const cpu = Number(metrics.cpu_percent ?? 0)
  const mem = Number(metrics.memory_percent ?? 0)
  const disk = Number(metrics.disk_percent ?? 0)

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      {err && <p className="text-nexus-danger text-sm">{err}</p>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {[{ label: 'CPU', value: cpu }, { label: 'Memória', value: mem }, { label: 'Disco', value: disk }].map(({ label, value }) => (
          <div key={label} className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
            <div className="flex justify-between mb-1">
              <span className="text-xs text-gray-400">{label}</span>
              <span className="text-sm font-mono">{value.toFixed(1)}%</span>
            </div>
            <Bar value={value} color={value > 80 ? '#ef4444' : value > 60 ? '#f59e0b' : '#3b82f6'} />
          </div>
        ))}
      </div>
      <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
        <p className="text-xs text-gray-400 mb-3">Módulos</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {Object.entries(status).map(([name, val]) => {
            const running = typeof val === 'string' ? val === 'running' : typeof val === 'object' && val !== null
            return (
              <div key={name} className="flex items-center gap-2 text-xs">
                <span className={`w-2 h-2 rounded-full shrink-0 ${running ? 'bg-nexus-success' : 'bg-nexus-danger'}`} />
                <span className="text-gray-300 truncate">{name}</span>
              </div>
            )
          })}
        </div>
      </div>
      <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4">
        <p className="text-xs text-gray-400 mb-2">Sistema</p>
        <div className="grid grid-cols-2 gap-1 text-xs">
          <span className="text-gray-500">RAM usada</span><span>{metrics.memory_used_mb} MB / {metrics.memory_total_mb} MB</span>
          <span className="text-gray-500">Disco livre</span><span>{metrics.disk_free_gb} GB</span>
        </div>
      </div>
    </div>
  )
}
