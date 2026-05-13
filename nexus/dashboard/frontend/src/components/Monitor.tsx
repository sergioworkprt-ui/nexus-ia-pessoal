import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api'

interface ServiceStatus { [service: string]: string }
interface PortStatus { [port: string]: boolean }
interface Resources {
  cpu_percent: number
  memory_percent: number
  memory_used_mb: number
  memory_total_mb: number
  disk_percent: number
  disk_free_gb: number
}
interface GitInfo { commit: string; branch: string; last_deploy: string }
interface AutohealInfo { consecutive_failures: number; last_action: string }
interface MonitorSnapshot {
  timestamp: string
  services: ServiceStatus
  ports: PortStatus
  resources: Resources
  git: GitInfo
  autoheal: AutohealInfo
}
interface AutohealStatus {
  consecutive_failures: number
  last_action: string
  last_check: string
  max_failures: number
}

function pctColor(v: number) {
  if (v < 60) return 'bg-green-500'
  if (v < 80) return 'bg-yellow-500'
  return 'bg-red-500'
}
function pctText(v: number) {
  if (v < 60) return 'text-green-400'
  if (v < 80) return 'text-yellow-400'
  return 'text-red-400'
}
function svcBg(s: string) {
  return s === 'active' ? 'bg-green-900/40 border-green-700' : 'bg-red-900/40 border-red-700'
}
function svcText(s: string) {
  return s === 'active' ? 'text-green-400' : 'text-red-400'
}

function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-400">{label}</span>
        <span className={pctText(value)}>{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${pctColor(value)}`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  )
}

function StatusDot({ active }: { active: boolean }) {
  return <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${active ? 'bg-green-400' : 'bg-red-400'}`} />
}

export default function Monitor() {
  const [data, setData] = useState<MonitorSnapshot | null>(null)
  const [history, setHistory] = useState<MonitorSnapshot[]>([])
  const [autoheal, setAutoheal] = useState<AutohealStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      const [status, hist, ah] = await Promise.allSettled([
        api.monitorStatus(),
        api.monitorHistory(),
        api.autohealStatus(),
      ])
      if (status.status === 'fulfilled') setData(status.value as MonitorSnapshot)
      if (hist.status === 'fulfilled') setHistory((hist.value as { history: MonitorSnapshot[] }).history ?? [])
      if (ah.status === 'fulfilled') setAutoheal(ah.value as AutohealStatus)
      setError(null)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
      setLastRefresh(new Date())
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchAll, 10_000)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, fetchAll])

  const exportJSON = () => {
    const blob = new Blob([JSON.stringify({ data, history, autoheal }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `nexus-monitor-${new Date().toISOString().slice(0, 19)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportMarkdown = () => {
    if (!data) return
    const r = data.resources
    const lines = [
      '# NEXUS Monitor Export',
      `**Timestamp**: ${data.timestamp}`,
      '',
      '## Services',
      ...Object.entries(data.services).map(([k, v]) => `- ${k}: **${v}**`),
      '',
      '## Ports',
      ...Object.entries(data.ports).map(([p, open]) => `- :${p}: ${open ? '✔ open' : '✘ closed'}`),
      '',
      '## Resources',
      `- CPU: ${r.cpu_percent.toFixed(1)}%`,
      `- Memory: ${r.memory_percent.toFixed(1)}% (${r.memory_used_mb}MB / ${r.memory_total_mb}MB)`,
      `- Disk: ${r.disk_percent.toFixed(1)}% (${r.disk_free_gb}GB free)`,
      '',
      '## Git',
      `- Commit: ${data.git.commit}`,
      `- Branch: ${data.git.branch}`,
      `- Last Deploy: ${data.git.last_deploy}`,
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `nexus-monitor-${new Date().toISOString().slice(0, 19)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <span className="animate-pulse">Loading monitor data...</span>
      </div>
    )
  }

  const allServicesOk = data ? Object.values(data.services).every(s => s === 'active') : false
  const allPortsOk = data ? Object.values(data.ports).every(Boolean) : false

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 space-y-4 text-sm">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">System Monitor</h2>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            allServicesOk && allPortsOk ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
          }`}>
            {allServicesOk && allPortsOk ? '● HEALTHY' : '● ISSUES DETECTED'}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {lastRefresh && (
            <span className="text-xs text-gray-500">Updated {lastRefresh.toLocaleTimeString()}</span>
          )}
          <button
            onClick={() => setAutoRefresh(v => !v)}
            className={`px-2 py-1 rounded text-xs ${
              autoRefresh ? 'bg-blue-700 text-blue-100' : 'bg-gray-700 text-gray-300'
            }`}
          >
            {autoRefresh ? '⏱ Auto 10s' : '⏸ Paused'}
          </button>
          <button onClick={fetchAll} className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600">
            ↻ Refresh
          </button>
          <button onClick={exportJSON} className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600">
            ↓ JSON
          </button>
          <button onClick={exportMarkdown} className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600">
            ↓ MD
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/40 border border-red-700 rounded p-3 text-red-300 text-xs">
          {error} — using cached data if available
        </div>
      )}

      {data && (
        <>
          {/* Services + Ports */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-gray-800 rounded-lg p-4 space-y-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Services</h3>
              {Object.entries(data.services).map(([svc, s]) => (
                <div key={svc} className={`flex items-center justify-between p-2 rounded border ${svcBg(s)}`}>
                  <span className="text-gray-200 font-mono text-xs">{svc}</span>
                  <span className={`text-xs font-semibold ${svcText(s)}`}>
                    {s === 'active' ? '✔ active' : `✘ ${s}`}
                  </span>
                </div>
              ))}
            </div>

            <div className="bg-gray-800 rounded-lg p-4 space-y-2">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Ports</h3>
              {[
                { port: '8000', label: 'nexus-core API' },
                { port: '8001', label: 'nexus-api REST' },
                { port: '8801', label: 'nexus-core WS' },
                { port: '9000', label: 'nexus-dashboard' },
              ].map(({ port, label }) => {
                const open = data.ports[port] ?? false
                return (
                  <div key={port} className={`flex items-center justify-between p-2 rounded border ${
                    open ? 'bg-green-900/30 border-green-700' : 'bg-red-900/30 border-red-700'
                  }`}>
                    <div>
                      <span className="text-gray-200 font-mono text-xs">:{port}</span>
                      <span className="text-gray-500 text-xs ml-2">{label}</span>
                    </div>
                    <span className={`text-xs font-semibold ${open ? 'text-green-400' : 'text-red-400'}`}>
                      {open ? '✔ open' : '✘ closed'}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Resources */}
          <div className="bg-gray-800 rounded-lg p-4 space-y-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Resources</h3>
            <ProgressBar value={data.resources.cpu_percent} label="CPU" />
            <ProgressBar
              value={data.resources.memory_percent}
              label={`Memory (${data.resources.memory_used_mb}MB / ${data.resources.memory_total_mb}MB)`}
            />
            <ProgressBar
              value={data.resources.disk_percent}
              label={`Disk (${data.resources.disk_free_gb}GB free)`}
            />
          </div>

          {/* Git + Autoheal */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-gray-800 rounded-lg p-4">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Deployment</h3>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-gray-400">Branch</span>
                  <span className="text-blue-300 font-mono">{data.git.branch}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Commit</span>
                  <span className="text-gray-200 font-mono">{data.git.commit}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Last Deploy</span>
                  <span className="text-gray-300">{data.git.last_deploy || 'unknown'}</span>
                </div>
              </div>
            </div>

            <div className="bg-gray-800 rounded-lg p-4">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Autoheal</h3>
              {autoheal ? (
                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Failures</span>
                    <span className={`font-semibold ${
                      autoheal.consecutive_failures === 0 ? 'text-green-400'
                      : autoheal.consecutive_failures < (autoheal.max_failures ?? 3) ? 'text-yellow-400'
                      : 'text-red-400'
                    }`}>
                      {autoheal.consecutive_failures} / {autoheal.max_failures ?? 3}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Last Action</span>
                    <span className="text-gray-200">{autoheal.last_action}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Last Check</span>
                    <span className="text-gray-400">{autoheal.last_check?.slice(0, 19) || 'never'}</span>
                  </div>
                </div>
              ) : (
                <span className="text-gray-500 text-xs">No autoheal data yet</span>
              )}
            </div>
          </div>

          {/* History table */}
          {history.length > 0 && (
            <div className="bg-gray-800 rounded-lg p-4">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                Resource History ({history.length} entries)
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-700">
                      <th className="pb-2 pr-4">Time (UTC)</th>
                      <th className="pb-2 pr-4">CPU%</th>
                      <th className="pb-2 pr-4">MEM%</th>
                      <th className="pb-2 pr-4">DISK%</th>
                      <th className="pb-2">Services</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...history].reverse().slice(0, 20).map((entry, i) => {
                      const ok = Object.values(entry.services).every(s => s === 'active')
                      return (
                        <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                          <td className="py-1 pr-4 text-gray-400 font-mono">{entry.timestamp?.slice(11, 19)}</td>
                          <td className={`py-1 pr-4 ${pctText(entry.resources.cpu_percent)}`}>
                            {entry.resources.cpu_percent.toFixed(1)}
                          </td>
                          <td className={`py-1 pr-4 ${pctText(entry.resources.memory_percent)}`}>
                            {entry.resources.memory_percent.toFixed(1)}
                          </td>
                          <td className={`py-1 pr-4 ${pctText(entry.resources.disk_percent)}`}>
                            {entry.resources.disk_percent.toFixed(1)}
                          </td>
                          <td className="py-1">
                            <StatusDot active={ok} />
                            {ok ? 'OK' : 'Issues'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {!data && !loading && (
        <div className="text-center text-gray-500 py-8">
          <p className="mb-2">No monitor data available.</p>
          <p className="text-xs">
            Run <code className="bg-gray-700 px-1 rounded">bash scripts/monitor_collect.sh</code> on the VPS to generate data.
          </p>
        </div>
      )}
    </div>
  )
}
