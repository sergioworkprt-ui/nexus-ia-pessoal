const BASE = (
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
).replace(/\/$/, '')

function token() { return localStorage.getItem('nexus_token') ?? '' }

async function req<T = unknown>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token()}`,
      ...(opts.headers ?? {}),
    },
  })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json() as Promise<T>
}

const post = <T = unknown>(path: string, body: unknown) =>
  req<T>(path, { method: 'POST', body: JSON.stringify(body) })

const del = <T = unknown>(path: string) =>
  req<T>(path, { method: 'DELETE' })

const put = <T = unknown>(path: string, body: unknown) =>
  req<T>(path, { method: 'PUT', body: JSON.stringify(body) })

export const api = {
  health: () => req('/health'),
  status: () => req('/status'),

  chat: (message: string, mode = 'normal') => post('/chat', { message, mode }),

  memory: (n = 50) => req(`/memory?n=${n}`),
  clearMemory: () => del('/memory'),

  tasks: (status?: string, type_?: string) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    if (type_) p.set('type_', type_)
    return req(`/tasks?${p}`)
  },
  createTask: (title: string, type_: string, payload = {}, needs_approval = false) =>
    post('/tasks', { title, type_, payload, needs_approval }),
  approveTask: (id: string) => post(`/tasks/${id}/approve`, {}),
  deleteTask: (id: string) => del(`/tasks/${id}`),

  learningMulti: (question: string) => post('/learning/multi', { question }),
  learningSynthesize: (question: string) => post('/learning/synthesize', { question }),
  learningProviders: () => req('/learning/providers'),

  videoAnalyze: (url: string, mode = 'full') => post('/video/analyze', { url, mode }),

  evolutionPropose: (description: string, target_file?: string) =>
    post('/evolution/propose', { description, target_file }),
  evolutionList: (status?: string) => {
    const p = new URLSearchParams()
    if (status) p.set('status', status)
    return req(`/evolution?${p}`)
  },
  evolutionApprove: (pid: string) => post(`/evolution/${pid}/approve`, {}),
  evolutionReject:  (pid: string) => post(`/evolution/${pid}/reject`, {}),
  evolutionApply:   (pid: string) => post(`/evolution/${pid}/apply`, {}),

  truthCheck: (claim: string) => post('/truth/check', { claim }),

  xtbStatus:    () => req('/trading/xtb/status'),
  xtbPositions: () => req('/trading/xtb/positions'),
  xtbBalance:   () => req('/trading/xtb/balance'),
  xtbOrder: (o: Record<string, unknown>) => post('/trading/xtb/order', o),

  ibkrStatus:    () => req('/trading/ibkr/status'),
  ibkrPositions: () => req('/trading/ibkr/positions'),
  ibkrAccount:   () => req('/trading/ibkr/account'),
  ibkrOrder: (o: Record<string, unknown>) => post('/trading/ibkr/order', o),

  enableReal: (code: string) => post('/trade/real/enable', { code }),

  verifyPin: (pin: string) => post<{ ok: boolean; token?: string }>('/security/pin/verify', { pin }),
  auditLog: (lines = 50) => req(`/security/audit?lines=${lines}`),
  securityStatus: () => req('/security/status'),

  metrics: () => req('/monitor/metrics'),
  monitorStatus: () => req('/monitor/status'),
  monitorHistory: (limit = 50) => req(`/monitor/history?limit=${limit}`),
  autohealStatus: () => req('/monitor/autoheal'),
  scaleStatus: () => req('/monitor/scale'),

  logs: (service: string, lines = 150) => req(`/logs/${service}?lines=${lines}`),

  getSettings: () => req('/settings'),
  saveSettings: (s: Record<string, unknown>) => put('/settings', s),
}

/**
 * URL do WebSocket do nexus-core.
 * - Usa VITE_WS_URL se definido (ex: ws://35.241.151.115:8801)
 * - Fallback local: porta 8801 (nexus-core WS), nunca derivada da API_PORT
 */
export const wsUrl = (): string => {
  const envWs = import.meta.env.VITE_WS_URL as string | undefined
  if (envWs) return envWs
  // Fallback dev local: extrai o host de BASE e usa porta 8801 (nexus-core WS)
  const host = BASE.replace(/^https?:\/\//, '').replace(/:\d+$/, '')
  return `ws://${host}:8801`
}
