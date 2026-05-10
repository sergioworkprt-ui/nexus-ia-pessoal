import React from 'react'
import type { AvatarState } from '../types'

const CFG = {
  idle:     { color: '#3b82f6', label: 'Standby',  rings: 1 },
  thinking: { color: '#f59e0b', label: 'A pensar', rings: 2 },
  speaking: { color: '#10b981', label: 'A falar',  rings: 3 },
} as const

interface Props {
  state: AvatarState
  size?: 'sm' | 'md' | 'lg'
}

export default function Avatar({ state, size = 'md' }: Props) {
  const cfg = CFG[state]
  const dim = size === 'sm' ? 'w-8 h-8' : size === 'lg' ? 'w-28 h-28' : 'w-16 h-16'
  const inner = size === 'sm' ? 'inset-1' : size === 'lg' ? 'inset-4' : 'inset-2'

  return (
    <div className={`relative ${dim} shrink-0`}>
      {Array.from({ length: cfg.rings }).map((_, i) => (
        <span
          key={i}
          className="absolute inset-0 rounded-full animate-ping"
          style={{
            border: `2px solid ${cfg.color}`,
            opacity: 0.25 - i * 0.07,
            animationDelay: `${i * 0.35}s`,
            animationDuration: `${1.4 + i * 0.3}s`,
          }}
        />
      ))}
      <div
        className={`absolute ${inner} rounded-full flex items-center justify-center`}
        style={{ background: `${cfg.color}18`, border: `2px solid ${cfg.color}` }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke={cfg.color} strokeWidth="1.5" className="w-full h-full p-1">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
        </svg>
      </div>
    </div>
  )
}
