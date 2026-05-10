import React from 'react'

interface Props {
  state: 'idle' | 'thinking' | 'speaking'
}

const STATE_CONFIG = {
  idle:     { color: '#3b82f6', label: 'Standby',   rings: 1 },
  thinking: { color: '#f59e0b', label: 'A pensar…', rings: 2 },
  speaking: { color: '#10b981', label: 'A falar…',  rings: 3 },
} as const

export default function Avatar({ state }: Props) {
  const cfg = STATE_CONFIG[state]

  return (
    <div className="bg-nexus-panel border border-nexus-border rounded-lg p-4 flex flex-col items-center gap-3">
      <div className="relative w-24 h-24">
        {Array.from({ length: cfg.rings }).map((_, i) => (
          <span
            key={i}
            className="absolute inset-0 rounded-full animate-ping"
            style={{
              border: `2px solid ${cfg.color}`,
              opacity: 0.3 - i * 0.08,
              animationDelay: `${i * 0.3}s`,
              animationDuration: `${1.5 + i * 0.3}s`,
            }}
          />
        ))}
        <div
          className="absolute inset-3 rounded-full flex items-center justify-center"
          style={{ backgroundColor: `${cfg.color}22`, border: `2px solid ${cfg.color}` }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke={cfg.color} strokeWidth="1.5"
               className="w-10 h-10">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
          </svg>
        </div>
      </div>
      <p className="text-xs tracking-widest uppercase" style={{ color: cfg.color }}>
        {cfg.label}
      </p>
    </div>
  )
}
