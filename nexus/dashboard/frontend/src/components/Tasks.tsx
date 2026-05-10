import React, { useEffect, useState } from 'react'
import type { Task } from '../types'
import { api } from '../api'

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-nexus-warning', done: 'text-nexus-success',
  failed: 'text-nexus-danger', waiting_approval: 'text-nexus-accent', running: 'text-blue-400',
}

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [title, setTitle] = useState('')
  const [type_, setType] = useState('manual')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    try {
      const r = await api.tasks() as { tasks: Task[] }
      setTasks(r.tasks)
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [])

  const create = async () => {
    if (!title.trim()) return
    setLoading(true)
    try {
      await api.createTask(title, type_, {}, false)
      setTitle('')
      await load()
    } finally { setLoading(false) }
  }

  const approve = async (id: string) => {
    await api.approveTask(id)
    await load()
  }

  const remove = async (id: string) => {
    await api.deleteTask(id)
    await load()
  }

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <div className="flex gap-2">
        <input className="flex-1 bg-nexus-panel border border-nexus-border rounded px-3 py-2 text-sm focus:outline-none focus:border-nexus-accent"
          placeholder="Nova tarefa…" value={title} onChange={e => setTitle(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && create()} />
        <select className="bg-nexus-panel border border-nexus-border rounded px-2 py-2 text-sm"
          value={type_} onChange={e => setType(e.target.value)}>
          {['manual','learning','analysis','trading','evolution','scheduled'].map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <button onClick={create} disabled={loading}
          className="px-4 py-2 bg-nexus-accent rounded text-sm font-semibold hover:bg-blue-500 disabled:opacity-40">
          + Criar
        </button>
      </div>
      <div className="flex-1 overflow-y-auto space-y-2">
        {tasks.length === 0 && <p className="text-gray-500 text-sm text-center mt-12">Sem tarefas.</p>}
        {tasks.map(t => (
          <div key={t.id} className="bg-nexus-panel border border-nexus-border rounded-lg p-3 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`text-xs font-semibold uppercase ${STATUS_COLOR[t.status] ?? 'text-gray-400'}`}>{t.status}</span>
                <span className="text-xs text-gray-500">[{t.type}]</span>
                <span className="text-xs text-gray-600 ml-auto">{t.id}</span>
              </div>
              <p className="text-sm truncate">{t.title}</p>
              {t.error && <p className="text-xs text-nexus-danger mt-1">{t.error}</p>}
              {t.result && <p className="text-xs text-nexus-success mt-1">{JSON.stringify(t.result).slice(0, 80)}</p>}
            </div>
            <div className="flex gap-1 shrink-0">
              {t.status === 'waiting_approval' && (
                <button onClick={() => approve(t.id)} className="px-2 py-1 bg-nexus-success/20 text-nexus-success rounded text-xs hover:bg-nexus-success/40">✓ Aprovar</button>
              )}
              <button onClick={() => remove(t.id)} className="px-2 py-1 bg-nexus-danger/20 text-nexus-danger rounded text-xs hover:bg-nexus-danger/40">✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
