import React, { useEffect, useState } from 'react'
import { api } from '../api'

export default function Settings() {
  const [settings, setSettings] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.getSettings().then(s => setSettings((s ?? {}) as Record<string, string>)).catch(() => {})
  }, [])

  const set = (k: string, v: string) => setSettings(prev => ({ ...prev, [k]: v }))

  const save = async () => {
    await api.saveSettings(settings)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const fields = [
    { k: 'persona', label: 'Persona', hint: 'JARVIS ou Friday' },
    { k: 'language', label: 'Idioma', hint: 'pt-PT ou en-US' },
    { k: 'tts_engine', label: 'Motor TTS', hint: 'gtts / elevenlabs / azure' },
    { k: 'chat_mode', label: 'Modo padrão', hint: 'normal / teacher / technical' },
    { k: 'trading_mode', label: 'Trading', hint: 'simulation / real' },
  ]

  return (
    <div className="p-6 max-w-lg space-y-4">
      <h2 className="text-nexus-accent font-semibold">Definições</h2>
      {fields.map(({ k, label, hint }) => (
        <div key={k}>
          <label className="block text-xs text-gray-400 mb-1">{label}</label>
          <input className="w-full bg-nexus-panel border border-nexus-border rounded px-3 py-2 text-sm focus:outline-none focus:border-nexus-accent"
            placeholder={hint} value={settings[k] ?? ''} onChange={e => set(k, e.target.value)} />
        </div>
      ))}
      <button onClick={save} className="px-4 py-2 bg-nexus-accent rounded text-sm font-semibold hover:bg-blue-500">
        {saved ? '✓ Guardado' : 'Guardar'}
      </button>
    </div>
  )
}
