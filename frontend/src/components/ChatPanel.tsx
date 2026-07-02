import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { ChatReference } from '../types'
import { ChunkModal } from './common'

interface Msg { role: 'user' | 'assistant'; content: string; refs?: ChatReference[] }

const SUGGESTIONS = [
  'Объясни главный диагноз',
  'Почему гипотеза №1 первая?',
  'Что неизвлекаемо и почему?',
]

export default function ChatPanel({ pid, onClose }: { pid: string; onClose: () => void }) {
  const nav = useNavigate()
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [chunk, setChunk] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const send = async (text: string) => {
    if (!text.trim() || busy) return
    const history = msgs.map(m => ({ role: m.role, content: m.content }))
    setMsgs(m => [...m, { role: 'user', content: text }])
    setInput('')
    setBusy(true)
    try {
      const ans = await api.chat(pid, text, history)
      setMsgs(m => [...m, { role: 'assistant', content: ans.text, refs: ans.references }])
    } catch (e) {
      setMsgs(m => [...m, { role: 'assistant', content: `Ошибка: ${e}` }])
    } finally { setBusy(false) }
  }

  const openRef = (r: ChatReference) => {
    if (r.type === 'chunk') setChunk(r.id)
    else if (r.type === 'hypothesis') nav(`/p/${pid}/hypotheses`)
    else nav(`/p/${pid}/map`)
  }

  const refLabel = (r: ChatReference) =>
    r.type === 'rule' ? `правило ${r.id}` :
    r.type === 'cell' ? `ячейка ${r.id}` :
    r.type === 'hypothesis' ? `гипотеза ${r.id.slice(0, 9)}` : `источник ${r.id.slice(0, 14)}…`

  return (
    <div className="fixed right-0 top-12 bottom-0 w-[26rem] bg-white border-l border-slate-200
        shadow-xl z-40 flex flex-col">
      <div className="p-3 border-b border-slate-200 flex items-center justify-between">
        <div className="font-semibold text-sm">💬 Ассистент проекта</div>
        <button className="btn" onClick={onClose}>✕</button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {msgs.length === 0 && (
          <div className="space-y-2">
            <div className="text-sm text-slate-500">
              Отвечаю на вопросы про этот отчёт, диагнозы и гипотезы — со ссылками на
              правила, ячейки и литературу.
            </div>
            {SUGGESTIONS.map(s => (
              <button key={s} className="badge bg-teal-50 text-teal-800 border border-teal-200
                  cursor-pointer hover:bg-teal-100 mr-1" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-sm text-left
                whitespace-pre-wrap leading-relaxed ${m.role === 'user'
                ? 'bg-teal-700 text-white' : 'bg-slate-100'}`}>
              {m.content}
            </div>
            {m.refs && m.refs.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {m.refs.map((r, n) => (
                  <button key={n} onClick={() => openRef(r)}
                    className="badge bg-white border border-teal-300 text-teal-800
                      cursor-pointer hover:bg-teal-50">
                    ↗ {refLabel(r)}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="text-sm text-slate-400 animate-pulse">думаю…</div>}
        <div ref={bottomRef} />
      </div>

      <form className="p-3 border-t border-slate-200 flex gap-2"
        onSubmit={e => { e.preventDefault(); send(input) }}>
        <input className="flex-1 border border-slate-300 rounded px-2 py-1.5 text-sm"
          placeholder="Вопрос про отчёт, диагнозы, гипотезы…"
          value={input} onChange={e => setInput(e.target.value)} disabled={busy} />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>→</button>
      </form>
      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
    </div>
  )
}
