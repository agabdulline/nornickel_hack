import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, fmt } from '../api'
import { notifyDataChanged, requestHighlight } from '../highlight'
import type { ChatAction, ChatChart, ChatMeta, ChatReference } from '../types'
import { ChunkModal, Icon, Chip, SectionLabel } from './common'

/** Предложенное ассистентом действие + его судьба после клика. */
interface ActionState {
  action: ChatAction
  status: 'offered' | 'running' | 'done' | 'failed'
  note?: string
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
  refs?: ChatReference[]
  charts?: ChatChart[]
  actions?: ActionState[]   // эфемерные: живут до перезагрузки панели
  followups?: string[]      // чипсы-продолжения (показываются у последнего ответа)
  error?: boolean           // сообщение-ошибка с кнопкой «Повторить»
  retryText?: string        // какой вопрос пересылать при ретрае
}

const SUGGESTIONS = [
  'Объясни главный диагноз',
  'Почему гипотеза №1 первая?',
  'Что неизвлекаемо и почему?',
  'Покажи график потерь по классам крупности',
]

// подсказки под конкретный экран (fallback — общие SUGGESTIONS)
const SUGGESTIONS_BY_PAGE: Record<string, string[]> = {
  report: [
    'Какие проблемы нашлись в данных отчёта?',
    'Что значат восстановленные значения?',
    'Объясни главный диагноз',
  ],
  map: [
    'Объясни главный диагноз',
    'Что неизвлекаемо и почему?',
    'Покажи график потерь по классам крупности',
  ],
  hypotheses: [
    'Почему гипотеза №1 первая?',
    'Сравни топ-3 гипотезы',
    'Какие гипотезы не требуют нового оборудования?',
  ],
  export: [
    'Когда стартуют испытания принятых гипотез?',
    'Почему стадии на дорожной карте сдвинуты?',
    'Что войдёт в DOCX-отчёт?',
  ],
}

// Подсказки для режима «без проекта» — общий вопрос к базе знаний.
const KB_SUGGESTIONS = [
  'Как извлекают золото из упорных руд?',
  'Что влияет на флотацию тонких шламов?',
  'Зачем доизмельчать сростки пентландита?',
]

/** Ссылка по тексту в квадратных скобках: сперва точное совпадение со списком
 *  references ответа, затем распознавание по форме id. */
function matchRef(inner: string, refs: ChatReference[]): ChatReference | null {
  const exact = refs.find(r => r.id === inner)
  if (exact) return exact
  if (/^R\d[а-яa-z]?$/i.test(inner)) return { type: 'rule', id: inner }
  if (/^[0-9a-f]{8,}:\d+$/i.test(inner)) return { type: 'chunk', id: inner }
  if (/^h\d{2}-[0-9a-f]+$/i.test(inner)) return { type: 'hypothesis', id: inner }
  if (inner.includes('/') && /\/(Ni|Cu)$/.test(inner)) return { type: 'cell', id: inner }
  const partial = refs.find(r => inner.includes(r.id))
  return partial ? { ...partial } : null
}

function RefLink({ label, refTarget, onRef }: {
  label: string; refTarget: ChatReference; onRef: (r: ChatReference) => void
}) {
  return (
    <button type="button" onClick={() => onRef(refTarget)}
      className="underline decoration-dotted underline-offset-2 cursor-pointer
        font-medium hover:opacity-80 text-left break-words"
      style={{ color: 'var(--c-brand)' }}>
      {label}
    </button>
  )
}

/** Инлайн-разметка: **жирный** и кликабельные [ссылки].
 *  Составная скобка [R1, +125/…, −125+71/…] разбивается на отдельные ссылки. */
function InlineMd({ text, refs, onRef }: {
  text: string; refs: ChatReference[]; onRef: (r: ChatReference) => void
}) {
  const parts = text.split(/(\[[^\][\n]{1,160}\]|\*\*[^*\n]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) return <b key={i}>{p.slice(2, -2)}</b>
        if (p.startsWith('[') && p.endsWith(']')) {
          const inner = p.slice(1, -1)
          const single = matchRef(inner, refs)
          if (single) return <RefLink key={i} label={inner} refTarget={single} onRef={onRef} />
          const pieces = inner.split(/\s*[,;]\s*/)
          if (pieces.length > 1) {
            const matched = pieces.map(x => [x, matchRef(x, refs)] as const)
            if (matched.some(([, r]) => r)) return (
              <span key={i}>
                {matched.map(([label, r], k) => (
                  <span key={k}>
                    {k > 0 && ', '}
                    {r ? <RefLink label={label} refTarget={r} onRef={onRef} /> : label}
                  </span>
                ))}
              </span>
            )
          }
        }
        return <span key={i}>{p}</span>
      })}
    </>
  )
}

const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l)
const isTableSep = (l: string) => /^\s*\|[\s:|-]+\|\s*$/.test(l)

/** Текст ответа блоками: markdown-таблицы + инлайн-разметка остального. */
function RichText({ text, refs, onRef }: {
  text: string; refs: ChatReference[]; onRef: (r: ChatReference) => void
}) {
  const lines = text.split('\n')
  const blocks: ({ kind: 'text'; content: string } | { kind: 'table'; rows: string[][] })[] = []
  let i = 0
  while (i < lines.length) {
    if (isTableRow(lines[i])) {
      const rows: string[][] = []
      while (i < lines.length && isTableRow(lines[i])) {
        if (!isTableSep(lines[i]))
          rows.push(lines[i].trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim()))
        i++
      }
      if (rows.length >= 2) blocks.push({ kind: 'table', rows })
      else blocks.push({ kind: 'text', content: rows.map(r => r.join(' | ')).join('\n') })
      continue
    }
    const buf: string[] = []
    while (i < lines.length && !isTableRow(lines[i])) { buf.push(lines[i]); i++ }
    blocks.push({ kind: 'text', content: buf.join('\n') })
  }
  return (
    <>
      {blocks.map((b, k) => b.kind === 'table' ? (
        <div key={k} className="overflow-x-auto my-2 not-italic">
          <table className="tbl text-[12.5px]">
            <thead>
              <tr>{b.rows[0].map((c, j) =>
                <th key={j}><InlineMd text={c} refs={refs} onRef={onRef} /></th>)}</tr>
            </thead>
            <tbody>
              {b.rows.slice(1).map((r, ri) => (
                <tr key={ri}>{r.map((c, j) =>
                  <td key={j}><InlineMd text={c} refs={refs} onRef={onRef} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <span key={k}><InlineMd text={b.content} refs={refs} onRef={onRef} /></span>
      ))}
    </>
  )
}

/** Горизонтальный бар-чарт: одна величина, тонкие бары со скруглённым концом
 *  данных, подписи и значения — текстовыми токенами (не цветом серии). */
function ChartBlock({ chart }: { chart: ChatChart }) {
  const data = chart.data.slice(0, 12)
  const max = Math.max(...data.map(d => Math.abs(d.value)), 1e-9)
  return (
    <div className="mt-2 rounded-lg border border-line bg-surface px-3 py-2.5 w-full">
      <div className="text-[12px] font-semibold mb-2">
        {chart.title}{chart.unit ? `, ${chart.unit}` : ''}
      </div>
      <div className="flex flex-col gap-1.5">
        {data.map((d, i) => (
          <div key={i} className="grid items-center gap-2"
            style={{ gridTemplateColumns: '5.5rem 1fr auto' }}
            title={`${d.label}: ${fmt.t(d.value)}${chart.unit ? ' ' + chart.unit : ''}`}>
            <div className="text-[11px] truncate" style={{ color: 'var(--c-muted)' }}>
              {d.label}
            </div>
            <div className="h-2 rounded-r-[4px] min-w-[2px]"
              style={{ width: `${Math.max(2, Math.abs(d.value) / max * 100)}%`,
                       background: 'var(--c-brand)' }} />
            <div className="num text-[11px]">{fmt.t(d.value)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Чат-ассистент. С `pid` — интерпретатор проекта; без `pid` (на главной) —
 *  эксперт по литературе БЗ. В обоих режимах — несколько диалогов с историей
 *  на сервере (переживает закрытие панели и перезагрузку). */
export default function ChatPanel({ pid, onClose }: { pid?: string; onClose: () => void }) {
  const nav = useNavigate()
  const { pathname } = useLocation()
  // какой экран проекта открыт — ассистент получает это с каждым вопросом
  const page = pathname.match(/^\/p\/[^/]+\/(report|map|hypotheses|export)/)?.[1]
  const kbMode = !pid
  const [chats, setChats] = useState<ChatMeta[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [histLoading, setHistLoading] = useState(true)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [chunk, setChunk] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const reqSeq = useRef(0)   // защита от гонок при переключении диалогов

  const listChats = useCallback(() => pid ? api.chats(pid) : api.kbChats(), [pid])
  const createChat = useCallback(() => pid ? api.chatCreate(pid) : api.kbChatCreate(), [pid])
  const removeChat = useCallback((cid: string) =>
    pid ? api.chatDelete(pid, cid) : api.kbChatDelete(cid), [pid])
  const fetchHistory = useCallback((cid: string) =>
    pid ? api.chatHistory(pid, cid) : api.kbChatHistory(cid), [pid])

  const mapHistory = (ms: { role: 'user' | 'assistant'; content: string
    references: ChatReference[]; charts?: ChatChart[] }[]): Msg[] =>
    ms.map(m => ({ role: m.role, content: m.content, refs: m.references, charts: m.charts }))

  const loadHistory = useCallback(async (cid: string | null) => {
    const seq = ++reqSeq.current
    if (!cid) { setMsgs([]); setHistLoading(false); return }
    setHistLoading(true)
    try {
      const h = await fetchHistory(cid)
      if (seq === reqSeq.current) setMsgs(mapHistory(h.messages))
    } catch { /* истории нет — чистый лист */ }
    finally { if (seq === reqSeq.current) setHistLoading(false) }
  }, [fetchHistory])

  // диалоги — с сервера; открываем самый свежий
  useEffect(() => {
    let live = true
    listChats()
      .then(cs => {
        if (!live) return
        setChats(cs)
        const first = cs[0]?.id ?? null
        setActive(first)
        loadHistory(first)
      })
      .catch(() => { if (live) setHistLoading(false) })
    return () => { live = false }
  }, [listChats, loadHistory])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy])

  const refreshChats = async () => {
    try { setChats(await listChats()) } catch { /* не критично */ }
  }

  const send = async (text: string, retry = false) => {
    if (!text.trim() || busy) return
    setMsgs(m => {
      const base = retry ? m.filter(x => !x.error) : m
      return retry ? base : [...base, { role: 'user', content: text }]
    })
    setInput('')
    setBusy(true)
    try {
      let cid = active
      if (!cid) {
        cid = (await createChat()).id
        setActive(cid)
      }
      if (pid) {
        const ans = await api.chat(pid, text, cid, page)
        setMsgs(m => [...m, {
          role: 'assistant', content: ans.text,
          refs: ans.references, charts: ans.charts,
          actions: (ans.actions ?? []).map(a => ({ action: a, status: 'offered' as const })),
          followups: ans.followups,
        }])
      } else {
        const ans = await api.kbChat(text, cid)
        const refs: ChatReference[] = ans.citations.map(c => ({ type: 'chunk', id: c.chunk_id }))
        setMsgs(m => [...m, { role: 'assistant', content: ans.answer, refs }])
      }
      refreshChats()   // подхватить авто-заголовок диалога
    } catch (e) {
      setMsgs(m => [...m, {
        role: 'assistant', error: true, retryText: text,
        content: `Не получилось ответить: ${e instanceof Error ? e.message : e}`,
      }])
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const newChat = () => {
    if (busy) return
    setActive(null)
    setMsgs([])
    setHistLoading(false)
    inputRef.current?.focus()
  }

  const switchChat = (cid: string) => {
    if (busy || cid === active) return
    setActive(cid)
    loadHistory(cid)
  }

  const deleteActiveChat = async () => {
    if (!active || busy) return
    if (!window.confirm('Удалить этот диалог?')) return
    try { await removeChat(active) } catch { /* мог быть уже удалён */ }
    const rest = chats.filter(c => c.id !== active)
    setChats(rest)
    const next = rest[0]?.id ?? null
    setActive(next)
    loadHistory(next)
  }

  const openRef = (r: ChatReference) => {
    if (r.type === 'chunk') { setChunk(r.id); return }
    if (!pid) return
    // экран подсветит цель на ~5 секунд (см. highlight.ts); если цель есть
    // на текущем экране (Гант, таблица минералогии) — подсвечиваем на месте
    requestHighlight({ type: r.type, id: r.id })
    if (r.type === 'hypothesis') {
      if (page !== 'export') nav(`/p/${pid}/hypotheses`)
    } else if (r.type === 'cell') {
      if (page !== 'report') nav(`/p/${pid}/map`)
    } else nav(`/p/${pid}/map`)
  }

  /** Выполнить предложенное ассистентом действие (кнопка = подтверждение). */
  const runAction = async (msgIdx: number, actIdx: number) => {
    const st = msgs[msgIdx]?.actions?.[actIdx]
    if (!pid || !st || st.status === 'running' || st.status === 'done') return
    const a = st.action
    const patch = (upd: Partial<ActionState>) => setMsgs(m => m.map((msg, i) =>
      i !== msgIdx ? msg : {
        ...msg,
        actions: msg.actions?.map((x, j) => j === actIdx ? { ...x, ...upd } : x),
      }))
    let reason = a.params.reason ?? ''
    if (a.type === 'reject_hypothesis' && !reason.trim()) {
      reason = window.prompt('Причина отклонения (уйдёт в стоп-лист регенерации):') ?? ''
      if (!reason.trim()) return
    }
    patch({ status: 'running' })
    try {
      let note = ''
      if (a.type === 'accept_hypothesis') {
        await api.feedback(a.params.id!, 'accept')
        note = 'Гипотеза принята'
      } else if (a.type === 'reject_hypothesis') {
        await api.feedback(a.params.id!, 'reject', reason)
        note = 'Гипотеза отклонена, причина ушла в стоп-лист'
      } else if (a.type === 'set_weights') {
        await api.rerank(pid, a.params.weights ?? {})
        note = 'Веса применены, список переранжирован'
      } else {
        await api.roadmapBuild(pid)
        note = 'Дорожная карта построена'
      }
      patch({ status: 'done', note })
      notifyDataChanged()   // открытые экраны перезагрузят данные
    } catch (e) {
      patch({ status: 'failed', note: e instanceof Error ? e.message : String(e) })
    }
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
            {kbMode ? 'Эксперт по обогащению · отвечает по литературе'
                    : 'Отвечает со ссылками на источники'}
          </div>
        </div>
        <div className="flex items-center gap-1 ml-auto shrink-0">
          <button className="btn btn-ghost !px-2" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
      </header>

      {/* Диалоги: переключить / новый / удалить (в обоих режимах) */}
      {(chats.length > 0 || active === null) && (
        <div className="flex items-center gap-1.5 px-4 py-2 border-b border-line shrink-0">
          <select className="input !h-8 !py-0 flex-1 min-w-0 text-[13px]"
            value={active ?? ''} disabled={busy}
            onChange={e => e.target.value ? switchChat(e.target.value) : newChat()}
            aria-label="Диалог">
            {active === null && <option value="">Новый диалог</option>}
            {chats.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
          <button className="btn btn-ghost !px-2 shrink-0" onClick={newChat} disabled={busy}
            title="Новый диалог" aria-label="Новый диалог">
            <Icon name="plus" className="w-4 h-4" />
          </button>
          {active && (
            <button className="btn btn-ghost !px-2 shrink-0" onClick={deleteActiveChat}
              disabled={busy} title="Удалить диалог" aria-label="Удалить диалог">
              <Icon name="trash" className="w-4 h-4" />
            </button>
          )}
        </div>
      )}

      {/* Лента сообщений */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {histLoading && (
          <div className="flex items-center gap-2 text-sm animate-pulse" style={{ color: 'var(--c-faint)' }}>
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: 'var(--c-brand)' }} />
            загружаю историю…
          </div>
        )}

        {!histLoading && msgs.length === 0 && (
          <div className="animate-fade">
            <div className="text-sm leading-relaxed" style={{ color: 'var(--c-muted)' }}>
              {kbMode
                ? 'Отвечаю на вопросы по обогащению — флотация, измельчение, реагентика — по книгам и статьям из базы знаний, с цитатами и номерами страниц. Вопросы по вашему отчёту и гипотезам — в чате внутри проекта.'
                : 'Отвечаю на вопросы про этот отчёт, диагнозы и гипотезы — со ссылками на правила, ячейки и литературу. Могу построить график и выполнить действие: принять гипотезу, изменить веса, собрать дорожную карту.'}
            </div>
            <div className="mt-5">
              <SectionLabel>С чего начать</SectionLabel>
              <div className="flex flex-col items-start gap-2 stagger">
                {(kbMode ? KB_SUGGESTIONS
                         : SUGGESTIONS_BY_PAGE[page ?? ''] ?? SUGGESTIONS).map(s => (
                  <Chip key={s} onClick={() => send(s)}>{s}</Chip>
                ))}
              </div>
            </div>
          </div>
        )}

        {msgs.map((m, i) => {
          const isUser = m.role === 'user'
          const isLast = i === msgs.length - 1
          return (
            <div key={i} className={`animate-in flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
              <div
                className={'max-w-[90%] px-3.5 py-2.5 text-sm text-left whitespace-pre-wrap leading-relaxed ' +
                  (isUser
                    ? 'rounded-2xl rounded-br-md text-white'
                    : 'rounded-2xl rounded-bl-md bg-surface-2 border ' +
                      (m.error ? 'border-danger' : 'border-line'))}
                style={isUser ? { background: 'var(--c-brand)' } : undefined}>
                {isUser
                  ? m.content
                  : <RichText text={m.content} refs={m.refs ?? []} onRef={openRef} />}
                {!isUser && (m.charts ?? []).map((c, n) => <ChartBlock key={n} chart={c} />)}
              </div>

              {/* предложенные действия — кнопка и есть подтверждение */}
              {(m.actions ?? []).length > 0 && (
                <div className="flex flex-col gap-1.5 mt-1.5 w-[90%]">
                  {m.actions!.map((st, n) => (
                    <div key={n} className="card-2 px-3 py-2 flex items-center gap-2 text-[13px]">
                      <span className="shrink-0" style={{ color: 'var(--c-brand)' }}>
                        <Icon name="spark" className="w-4 h-4" />
                      </span>
                      <span className="flex-1 min-w-0 leading-snug">
                        {st.action.label || st.action.type}
                        {st.note && (
                          <span className="block text-[11px]"
                            style={{ color: st.status === 'failed' ? 'var(--c-danger)' : 'var(--c-ok)' }}>
                            {st.status === 'done' ? '✓ ' : ''}{st.note}
                          </span>
                        )}
                      </span>
                      {st.status !== 'done' && (
                        <button className="btn btn-primary btn-sm shrink-0"
                          disabled={st.status === 'running'}
                          onClick={() => runAction(i, n)}>
                          {st.status === 'running' ? '…'
                            : st.status === 'failed' ? 'Повторить' : 'Выполнить'}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {m.error && m.retryText && (
                <div className="mt-1.5">
                  <Chip onClick={() => send(m.retryText!, true)}>
                    <Icon name="refresh" className="w-3.5 h-3.5" /> Повторить
                  </Chip>
                </div>
              )}
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

              {/* продолжения разговора — только у последнего ответа */}
              {isLast && !isUser && !busy && (m.followups ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {m.followups!.map(f => (
                    <Chip key={f} onClick={() => send(f)}>{f}</Chip>
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
        <input ref={inputRef} className="input flex-1" autoFocus
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
