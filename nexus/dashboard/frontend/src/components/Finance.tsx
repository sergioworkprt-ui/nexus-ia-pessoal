import React, { useEffect, useState } from 'react'
import { api } from '../api'

function StatusBadge({ connected }: { connected: boolean }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${
      connected ? 'bg-nexus-success/20 text-nexus-success' : 'bg-nexus-danger/20 text-nexus-danger'
    }`}>{connected ? 'Ligado' : 'Desligado'}</span>
  )
}

function BrokerCard({
  title, status, positions, balance, onOrder
}: {
  title: string
  status: Record<string, unknown>
  positions: unknown[]
  balance: Record<string, unknown>
  onOrder: (o: Record<string, unknown>) => void
}) {
  const [sym, setSym] = useState('')
  const [vol, setVol] = useState('0.01')
  const [cmd, setCmd] = useState('0')

  return (
    <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-nexus-accent">{title}</h3>
        <StatusBadge connected={Boolean(status.connected)} />
      </div>
      <div className="grid grid-cols-2 gap-1 text-xs">
        {Object.entries(status).slice(0, 6).map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <span className="text-gray-500">{k}</span>
            <span className="text-gray-300">{String(v)}</span>
          </div>
        ))}
      </div>
      {Object.keys(balance).length > 0 && (
        <div className="bg-nexus-bg rounded p-2 text-xs">
          {Object.entries(balance).slice(0, 4).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-gray-500">{k}</span>
              <span>{String(v)}</span>
            </div>
          ))}
        </div>
      )}
      <div>
        <p className="text-xs text-gray-400 mb-1">Posições ({(positions as unknown[]).length})</p>
        {(positions as Record<string, unknown>[]).slice(0, 5).map((p, i) => (
          <div key={i} className="text-xs flex gap-2 py-0.5 border-b border-nexus-border">
            <span className="font-mono">{String(p.symbol ?? p.Symbol ?? '?')}</span>
            <span className="text-gray-400">{String(p.side ?? p.cmd ?? '')}</span>
            <span className="ml-auto">{String(p.size ?? p.volume ?? '')}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-1">
        <input className="flex-1 bg-nexus-bg border border-nexus-border rounded px-2 py-1 text-xs" placeholder="Symbol" value={sym} onChange={e => setSym(e.target.value)} />
        <input className="w-16 bg-nexus-bg border border-nexus-border rounded px-2 py-1 text-xs" placeholder="Vol" value={vol} onChange={e => setVol(e.target.value)} />
        <select className="bg-nexus-bg border border-nexus-border rounded px-1 py-1 text-xs" value={cmd} onChange={e => setCmd(e.target.value)}>
          <option value="0">BUY</option><option value="1">SELL</option>
        </select>
        <button onClick={() => sym && onOrder({ symbol: sym, cmd: Number(cmd), volume: Number(vol) })}
          className="px-2 py-1 bg-nexus-accent rounded text-xs hover:bg-blue-500">▶</button>
      </div>
    </div>
  )
}

export default function Finance() {
  const [xtbStatus, setXtbStatus] = useState<Record<string, unknown>>({})
  const [xtbPositions, setXtbPositions] = useState<unknown[]>([])
  const [xtbBalance, setXtbBalance] = useState<Record<string, unknown>>({})
  const [ibkrStatus, setIbkrStatus] = useState<Record<string, unknown>>({})
  const [ibkrPositions, setIbkrPositions] = useState<unknown[]>([])
  const [ibkrAccount, setIbkrAccount] = useState<Record<string, unknown>>({})
  const [realCode, setRealCode] = useState('')
  const [realMsg, setRealMsg] = useState('')

  const load = async () => {
    await Promise.allSettled([
      api.xtbStatus().then(r => setXtbStatus(r as Record<string, unknown>)),
      api.xtbPositions().then(r => setXtbPositions((r as { positions: unknown[] }).positions ?? [])),
      api.xtbBalance().then(r => setXtbBalance(r as Record<string, unknown>)),
      api.ibkrStatus().then(r => setIbkrStatus(r as Record<string, unknown>)),
      api.ibkrPositions().then(r => setIbkrPositions((r as { positions: unknown[] }).positions ?? [])),
      api.ibkrAccount().then(r => setIbkrAccount(r as Record<string, unknown>)),
    ])
  }

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [])

  const enableReal = async () => {
    const r = await api.enableReal(realCode) as { authorized: boolean; warning: string }
    setRealMsg(r.authorized ? `✓ ${r.warning}` : `✗ ${r.warning}`)
  }

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <BrokerCard title="XTB" status={xtbStatus} positions={xtbPositions} balance={xtbBalance}
          onOrder={o => api.xtbOrder(o).catch(e => alert(String(e)))} />
        <BrokerCard title="IBKR" status={ibkrStatus} positions={ibkrPositions} balance={ibkrAccount}
          onOrder={o => api.ibkrOrder({ ...o, action: o.cmd === 0 ? 'BUY' : 'SELL', quantity: o.volume }).catch(e => alert(String(e)))} />
      </div>
      <div className="bg-nexus-panel border border-nexus-danger/30 rounded-lg p-4">
        <h3 className="text-nexus-danger text-sm font-semibold mb-2">⚠️ Ativar Modo Real</h3>
        <div className="flex gap-2">
          <input type="password" className="flex-1 bg-nexus-bg border border-nexus-border rounded px-3 py-2 text-sm"
            placeholder="Código de confirmação" value={realCode} onChange={e => setRealCode(e.target.value)} />
          <button onClick={enableReal} className="px-4 py-2 bg-nexus-danger/20 text-nexus-danger rounded text-sm hover:bg-nexus-danger/40">Ativar</button>
        </div>
        {realMsg && <p className={`mt-1 text-xs ${realMsg.startsWith('✓') ? 'text-nexus-success' : 'text-nexus-danger'}`}>{realMsg}</p>}
      </div>
    </div>
  )
}
