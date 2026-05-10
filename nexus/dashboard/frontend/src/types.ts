export interface Message {
  role: 'user' | 'nexus'
  content: string
  ts: number
  mode?: string
}

export interface Task {
  id: string
  title: string
  type: string
  status: string
  payload: Record<string, unknown>
  result: unknown
  error: string | null
  created_at: string
  updated_at: string
}

export interface Proposal {
  id: string
  description: string
  target_file: string | null
  status: string
  analysis: {
    summary: string
    risks: string
    approach: string
    files_affected: string[]
  }
  created_at: string
  applied_at: string | null
}

export interface Position {
  symbol: string
  side: string
  size: number
  entry_price?: number
  avg_cost?: number
  pnl?: number
  broker: string
}

export type AvatarState = 'idle' | 'thinking' | 'speaking'

export type Tab =
  | 'chat' | 'tasks' | 'memory' | 'settings'
  | 'security' | 'finance' | 'learning' | 'monitor'
  | 'video' | 'logs' | 'evolution' | 'about'
