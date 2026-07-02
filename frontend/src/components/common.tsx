import { useEffect, useState } from 'react'
import { api } from '../api'

export function Spinner({ label = 'Загрузка…' }: { label?: string }) {
  return <div className="text-slate-500 text-sm py-8 text-center animate-pulse">{label}</div>
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="card p-3 text-sm text-red-700 bg-red-50 border-red-200">{error}</div>
}

export function EmptyBox({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="card p-8 text-center text-slate-500">
      <div>{text}</div>
      {hint && <div className="text-sm mt-1 text-slate-400">{hint}</div>}
    </div>
  )
}

export function CapexBadge({ capex }: { capex?: unknown }) {
  const v = String(capex ?? 'med').toLowerCase()
  const map: Record<string, [string, string]> = {
    low: ['CAPEX низкий', 'bg-green-100 text-green-800'],
    med: ['CAPEX средний', 'bg-slate-100 text-slate-700'],
    medium: ['CAPEX средний', 'bg-slate-100 text-slate-700'],
    high: ['CAPEX высокий', 'bg-amber-100 text-amber-800'],
  }
  const [label, cls] = map[v] ?? map.med
  return <span className={`badge ${cls}`}>{label}</span>
}

/** Модалка с текстом чанка-источника (клик по цитате). */
export function ChunkModal({ chunkId, quote, onClose }:
  { chunkId: string; quote?: string; onClose: () => void }) {
  const [chunk, setChunk] = useState<{ text: string; source: string; page_start: number } | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api.kbChunk(chunkId).then(setChunk).catch(e => setErr(String(e)))
  }, [chunkId])

  const hl = (text: string) => {
    if (!quote) return text
    const probe = quote.split(' ').slice(0, 6).join(' ')
    const i = text.toLowerCase().indexOf(probe.toLowerCase())
    if (i < 0) return text
    return (<>
      {text.slice(0, i)}
      <mark className="bg-teal-100">{text.slice(i, i + quote.length)}</mark>
      {text.slice(i + quote.length)}
    </>)
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-6"
      onClick={onClose}>
      <div className="card max-w-2xl w-full max-h-[80vh] overflow-auto p-4"
        onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-2">
          <div className="font-semibold">
            {chunk ? `${chunk.source}, с. ${chunk.page_start}` : chunkId}
          </div>
          <button className="btn" onClick={onClose}>✕</button>
        </div>
        {err && <div className="text-red-600 text-sm">{err}</div>}
        <div className="text-sm whitespace-pre-wrap leading-relaxed">
          {chunk ? hl(chunk.text) : 'Загрузка…'}
        </div>
      </div>
    </div>
  )
}
