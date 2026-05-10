import type { AvatarState } from '../types'

const CFG = {
  idle:     { color: '#3b82f6', rings: 1 },
  thinking: { color: '#f59e0b', rings: 2 },
  speaking: { color: '#10b981', rings: 3 },
} as const

const SIZES = { sm: 32, md: 64, lg: 112, logo: 152 } as const

interface Props {
  state: AvatarState
  size?: keyof typeof SIZES
}

export default function Avatar({ state, size = 'md' }: Props) {
  const cfg = CFG[state]
  const px  = SIZES[size]
  const pad = Math.round(px * 0.12)

  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-full"
      style={{ width: px, height: px }}
    >
      {Array.from({ length: cfg.rings }).map((_, i) => (
        <span
          key={i}
          className="absolute inset-0 rounded-full animate-ping"
          style={{
            border: `2px solid ${cfg.color}`,
            opacity: 0.30 - i * 0.08,
            animationDelay:    `${i * 0.35}s`,
            animationDuration: `${1.4 + i * 0.3}s`,
          }}
        />
      ))}
      <div
        className="absolute rounded-full flex items-center justify-center"
        style={{
          top:    pad,
          right:  pad,
          bottom: pad,
          left:   pad,
          background: `${cfg.color}18`,
          border: `2px solid ${cfg.color}`,
        }}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke={cfg.color}
          strokeWidth="1.5"
          className="w-full h-full p-1"
        >
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
        </svg>
      </div>
    </div>
  )
}
