import React, { useEffect, useState } from 'react'

interface Position {
  symbol: string
  side: string
  size: number
  entry_price: number
  current_price: number
  pnl: number
  broker: string
}

export default function TradingPanel() {
  const [positions, setPositions] = useState<Position[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch('/api/positions')
        const data = await r.json()
        setPositions(data.positions ?? [])
        setError(null)
      } catch {
        setError('Sem ligação ao NEXUS')
      }
    }
    load()
    const id = setInterval(load, 5_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex flex-col bg-nexus-panel border border-nexus-border rounded-lg overflow-hidden h-full">
      <div className="px-4 py-3 border-b border-nexus-border text-sm font-semibold text-nexus-accent">
        Posições Abertas
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {error && (
          <p className="text-xs text-nexus-danger text-center mt-8">{error}</p>
        )}
        {!error && positions.length === 0 && (
          <p className="text-xs text-gray-500 text-center mt-8">Sem posições abertas</p>
        )}
        {positions.map((p, i) => (
          <div key={i} className="mb-3 p-3 bg-nexus-bg border border-nexus-border rounded-lg">
            <div className="flex justify-between items-center mb-1">
              <span className="font-semibold text-sm">{p.symbol}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                p.side === 'BUY'
                  ? 'bg-nexus-success/20 text-nexus-success'
                  : 'bg-nexus-danger/20 text-nexus-danger'
              }`}>{p.side}</span>
            </div>
            <div className="grid grid-cols-2 gap-1 text-xs text-gray-400">
              <span>Size: {p.size}</span>
              <span>Broker: {p.broker}</span>
              <span>Entry: {p.entry_price}</span>
              <span>Now: {p.current_price}</span>
            </div>
            <div className={`text-sm font-bold mt-1 ${
              p.pnl >= 0 ? 'text-nexus-success' : 'text-nexus-danger'
            }`}>
              P&L: {p.pnl >= 0 ? '+' : ''}{p.pnl.toFixed(2)}€
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
