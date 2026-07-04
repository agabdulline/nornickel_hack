import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { ChatReference } from '../types'
import { ChunkModal, Icon, Chip, SectionLabel } from './common'

interface Msg { role: 'user' | 'assistant'; content: string; refs?: ChatReference[] }

const SUGGESTIONS = [
  'Объясни главный диагноз',
  'Почему гипотеза №1 первая?',
  'Что неизвлекаемо и почему?',
]

// Подсказки для режима «без проекта» — общий вопрос к базе знаний.
const KB_SUGGESTIONS = [
  'Как извлекают золото из упорных руд?',
  'Что влияет на флотацию тонких шламов?',
  'Зачем доизмельчать сростки пентландита?',
]

/** Чат-ассистент. С `pid` — интерпретатор проекта (отчёт/диагнозы/гипотезы);
 *  без `pid` (напр. на главной) — общий вопрос к базе знаний с цитатами. */
export default function ChatPanel({ pid, onClose }: { pid?: string; onClose: () => void }) {
  const nav = useNavigate()
  const kbMode = !pid
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
      if (pid) {
        const ans = await api.chat(pid, text, history)
        setMsgs(m => [...m, { role: 'assistant', content: ans.text, refs: ans.references }])
      } else {
        const ans = await api.kbAsk(text)
        const refs: ChatReference[] = ans.citations.map(c => ({ type: 'chunk', id: c.chunk_id }))
        setMsgs(m => [...m, { role: 'assistant', content: ans.answer, refs }])
      }
    } catch (e) {
      setMsgs(m => [...m, { role: 'assistant', content: `Ошибка: ${e}` }])
    } finally { setBusy(false) }
  }

  const openRef = (r: ChatReference) => {
    if (r.type === 'chunk') setChunk(r.id)
    else if (!pid) return
    else if (r.type === 'hypothesis') nav(`/p/${pid}/hypotheses`)
    else nav(`/p/${pid}/map`)
  }

  const refLabel = (r: ChatReference) =>
    r.type === 'rule' ? `правило ${r.id}` :
    r.type === 'cell' ? `ячейка ${r.id}` :
    r.type === 'hypothesis' ? `гипотеза ${r.id.slice(0, 9)}` : `источник ${r.id.slice(0, 14)}…`

  return (
    <aside className="fixed right-0 top-14 bottom-0 w-[26rem] max-w-full bg-surface border-l border-line
        z-40 flex flex-col animate-in" style={{ boxShadow: 'var(--shadow-pop)' }}>

      {/* Шапка */}
      <header className="flex items-center gap-2.5 px-4 py-3 border-b border-line shrink-0">
        <span className="grid place-items-center w-8 h-8 rounded-full shrink-0"
          style={{ background: 'var(--c-brand-tint)', color: 'var(--c-brand)' }}>
          <Icon name="chat" className="w-[18px] h-[18px]" />
        </span>
        <div className="min-w-0">
          <div className="font-bold text-sm leading-tight truncate">
            {kbMode ? 'Ассистент · база знаний' : 'Ассистент проекта'}
          </div>
          <div className="text-[11px] leading-tight" style={{ color: 'var(--c-faint)' }}>
            {kbMode ? 'Отвечает по литературе с цитатами' : 'Отвечает со ссылками на источники'}
          </div>
        </div>
        <button className="btn btn-ghost !px-2 ml-auto shrink-0" onClick={onClose} aria-label="Закрыть">
          <Icon name="x" />
        </button>
      </header>

      {/* Лента сообщений */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {msgs.length === 0 && (
          <div className="animate-fade">
            <div className="text-sm leading-relaxed" style={{ color: 'var(--c-muted)' }}>
              {kbMode
                ? 'Отвечаю на вопросы по базе знаний — с цитатами из литературы и номерами страниц.'
                : 'Отвечаю на вопросы про этот отчёт, диагнозы и гипотезы — со ссылками на правила, ячейки и литературу.'}
            </div>
            <div className="mt-5">
              <SectionLabel>С чего начать</SectionLabel>
              <div className="flex flex-col items-start gap-2 stagger">
                {(kbMode ? KB_SUGGESTIONS : SUGGESTIONS).map(s => (
                  <Chip key={s} onClick={() => send(s)}>{s}</Chip>
                ))}
              </div>
            </div>
          </div>
        )}

        {msgs.map((m, i) => {
          const isUser = m.role === 'user'
          return (
            <div key={i} className={`animate-in flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
              <div
                className={'max-w-[90%] px-3.5 py-2.5 text-sm text-left whitespace-pre-wrap leading-relaxed ' +
                  (isUser
                    ? 'rounded-2xl rounded-br-md text-white'
                    : 'rounded-2xl rounded-bl-md bg-surface-2 border border-line')}
                style={isUser ? { background: 'var(--c-brand)' } : undefined}>
                {m.content}
              </div>
              {m.refs && m.refs.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {m.refs.map((r, n) => (
                    <button key={n} type="button" onClick={() => openRef(r)}
                      className="badge badge-outline cursor-pointer transition-colors
                        hover:border-brand hover:text-brand">
                      <Icon name="arrowRight" className="w-3 h-3" />
                      {refLabel(r)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {busy && (
          <div className="flex items-center gap-2 text-sm animate-pulse" style={{ color: 'var(--c-faint)' }}>
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: 'var(--c-brand)' }} />
            думаю…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Форма ввода */}
      <form className="flex items-center gap-2 px-4 py-3 border-t border-line shrink-0"
        onSubmit={e => { e.preventDefault(); send(input) }}>
        <input className="input flex-1"
          placeholder={kbMode ? 'Вопрос к базе знаний…' : 'Вопрос про отчёт, диагнозы, гипотезы…'}
          value={input} onChange={e => setInput(e.target.value)} disabled={busy} />
        <button className="btn btn-primary !px-3 shrink-0" disabled={busy || !input.trim()}
          aria-label="Отправить">
          <Icon name="arrowRight" />
        </button>
      </form>

      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
    </aside>
  )
}
