import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import { api } from '../api'
import { useTheme } from '../theme'

/* ==========================================================================
   Дизайн-система «Фабрика гипотез» — переиспользуемые компоненты.
   Стилевые токены — в index.css (сине-центричная палитра nornickel,
   крупные радиусы, тема light/dark). Здесь — React-обёртки над классами.
   ========================================================================== */

/* --------------------------------- Иконки -------------------------------- */
const ICONS: Record<string, ReactNode> = {
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  chat: <path d="M21 11.5a8.4 8.4 0 0 1-11.9 7.6L3 21l1.9-6.1A8.4 8.4 0 1 1 21 11.5z" />,
  upload: <><path d="M12 15V3M7 8l5-5 5 5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></>,
  download: <><path d="M12 3v12M7 10l5 5 5-5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></>,
  check: <path d="M20 6 9 17l-5-5" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  arrowRight: <path d="M5 12h14M13 6l6 6-6 6" />,
  spark: <path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3" />,
  flask: <><path d="M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.3 2.3h11.4A1.5 1.5 0 0 0 19 19l-5-10V3" /><path d="M7.5 14h9" /></>,
  book: <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5zM19 19H6" />,
  lock: <><rect x="4.5" y="10" width="15" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
  alert: <><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>,
  refresh: <path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" />,
  doc: <><path d="M14 3v5h5" /><path d="M6 3h8l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  map: <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14" />,
  factory: <><path d="M3 21h18M4 21V10l6 4V10l6 4V6l4 2v13" /><path d="M8 21v-4M13 21v-4" /></>,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  target: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3.5" /></>,
  trash: <><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6M14 11v6" /></>,
}

export function Icon({ name, className = 'w-4 h-4', strokeWidth = 2 }:
  { name: keyof typeof ICONS | string; className?: string; strokeWidth?: number }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {ICONS[name] ?? null}
    </svg>
  )
}

/* --------------------------------- Логотип ------------------------------- */
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5 select-none">
      <img src="/norm-logo.png" alt="Фабрика гипотез" className="h-8 w-auto shrink-0" />
      {!compact && (
        <span className="font-extrabold tracking-tight text-[15px] leading-none"
          style={{ color: 'var(--c-brand-strong)' }}>
          Фабрика&nbsp;гипотез
        </span>
      )}
    </span>
  )
}

/* ------------------------------ Переключатель темы ----------------------- */
export function ThemeToggle() {
  const [theme, toggle] = useTheme()
  return (
    <button className="btn btn-ghost !px-2" onClick={toggle}
      title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'} aria-label="Переключить тему">
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} className="w-[18px] h-[18px]" />
    </button>
  )
}

/* --------------------------------- Бейдж --------------------------------- */
type Tone = 'default' | 'brand' | 'ok' | 'warn' | 'danger' | 'solid' | 'outline'
const TONE_CLASS: Record<Tone, string> = {
  default: '', brand: 'badge-brand', ok: 'badge-ok', warn: 'badge-warn',
  danger: 'badge-danger', solid: 'badge-solid', outline: 'badge-outline',
}
export function Badge({ tone = 'default', className = '', children, title }:
  { tone?: Tone; className?: string; children: ReactNode; title?: string }) {
  return <span className={`badge ${TONE_CLASS[tone]} ${className}`} title={title}>{children}</span>
}

/* --------------------------------- Чип ----------------------------------- */
export function Chip({ active = false, onClick, children, title }:
  { active?: boolean; onClick?: () => void; children: ReactNode; title?: string }) {
  return (
    <button type="button" title={title} onClick={onClick}
      className={`chip ${active ? 'chip-active' : ''}`}>{children}</button>
  )
}

/* --------------------------- KPI / стат-карточка ------------------------- */
export function StatCard({ label, value, sub, tone = 'default', icon }: {
  label: string; value: ReactNode; sub?: ReactNode
  tone?: 'default' | 'loss' | 'ok' | 'brand'; icon?: string
}) {
  const valColor = tone === 'loss' ? 'var(--c-danger)' : tone === 'ok' ? 'var(--c-ok)'
    : tone === 'brand' ? 'var(--c-brand-strong)' : 'var(--c-text)'
  return (
    <div className="card p-4 hover-lift relative overflow-hidden">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[11px] uppercase tracking-wide font-semibold" style={{ color: 'var(--c-muted)' }}>
          {label}
        </div>
        {icon && <Icon name={icon} className="w-4 h-4 opacity-40 shrink-0" />}
      </div>
      <div className="num text-2xl font-extrabold mt-1.5" style={{ color: valColor }}>{value}</div>
      {sub && <div className="num text-xs mt-0.5" style={{ color: 'var(--c-faint)' }}>{sub}</div>}
    </div>
  )
}

/* ---------------------- Сегментированный переключатель ------------------- */
export function Segmented<T extends string>({ options, value, onChange }: {
  options: readonly (T | { value: T; label: ReactNode })[]
  value: T; onChange: (v: T) => void
}) {
  return (
    <div className="seg">
      {options.map(o => {
        const val = (typeof o === 'object' ? o.value : o) as T
        const label = typeof o === 'object' ? o.label : o
        return (
          <button key={val} type="button" onClick={() => onChange(val)}
            className={`seg-btn ${value === val ? 'seg-btn-active' : ''}`}>{label}</button>
        )
      })}
    </div>
  )
}

/* -------------------------- Степпер (шаги проекта) ----------------------- */
export function Stepper({ pid, steps }: {
  pid: string; steps: { path: string; label: string; num: number }[]
}) {
  return (
    <nav className="flex items-center gap-1">
      {steps.map((s, i) => (
        <div key={s.path} className="flex items-center">
          {i > 0 && <span className="mx-0.5 opacity-30"><Icon name="arrowRight" className="w-3.5 h-3.5" /></span>}
          <NavLink to={`/p/${pid}/${s.path}`}
            className={({ isActive }) =>
              'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-semibold transition-all ' +
              (isActive ? 'text-white shadow-sm' : 'hover:bg-surface-2')}
            style={({ isActive }) => isActive
              ? { background: 'var(--c-brand)', color: '#fff' }
              : { color: 'var(--c-muted)' }}>
            {({ isActive }) => (<>
              <span className={'num grid place-items-center w-5 h-5 rounded-full text-[11px] ' +
                (isActive ? 'bg-white/25' : '')}
                style={isActive ? {} : { background: 'var(--c-surface-2)', color: 'var(--c-muted)' }}>
                {s.num}
              </span>
              <span className="hidden sm:inline">{s.label}</span>
            </>)}
          </NavLink>
        </div>
      ))}
    </nav>
  )
}

/* --------------------------- Панель (карточка с шапкой) ------------------ */
export function Panel({ title, subtitle, actions, children, className = '', bodyClass = 'p-4' }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode
  children: ReactNode; className?: string; bodyClass?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-center gap-3 px-4 py-3 border-b" style={{ borderColor: 'var(--c-line)' }}>
          <div className="min-w-0">
            {title && <h3 className="font-bold text-sm truncate">{title}</h3>}
            {subtitle && <div className="text-xs mt-0.5" style={{ color: 'var(--c-faint)' }}>{subtitle}</div>}
          </div>
          {actions && <div className="ml-auto flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="text-[11px] font-bold uppercase tracking-wider mb-2"
    style={{ color: 'var(--c-muted)' }}>{children}</div>
}

/** Единая шапка экрана: заголовок (+ подзаголовок) слева, действия справа. */
export function PageHeader({ title, subtitle, actions }: {
  title: ReactNode; subtitle?: ReactNode; actions?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-3 flex-wrap mb-1">
      <div className="min-w-0">
        <h1 className="text-2xl font-extrabold tracking-tight leading-tight">{title}</h1>
        {subtitle && <p className="text-sm mt-0.5" style={{ color: 'var(--c-muted)' }}>{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap shrink-0">{actions}</div>}
    </div>
  )
}

/* ------------------------------- Метр / бар ------------------------------ */
export function Meter({ value, className = '', title }: { value: number; className?: string; title?: string }) {
  return (
    <div className={`meter ${className}`} title={title}>
      <i style={{ width: `${Math.max(0, Math.min(value, 1)) * 100}%` }} />
    </div>
  )
}

/* ------------------------- Состояния (loading/empty/error) --------------- */
export function Spinner({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3" style={{ color: 'var(--c-faint)' }}>
      <img src="/norm-logo.png" alt="" aria-hidden
        className="w-12 h-12 object-contain animate-spin"
        style={{ animationDuration: '1.1s' }} />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="card p-3 flex items-start gap-2.5 text-sm"
      style={{ background: 'var(--c-danger-tint)', borderColor: 'color-mix(in srgb, var(--c-danger) 30%, transparent)', color: 'var(--c-danger)' }}>
      <Icon name="alert" className="w-4 h-4 mt-0.5 shrink-0" />
      <span>{error}</span>
    </div>
  )
}

export function EmptyBox({ text, hint, icon = 'doc' }: { text: string; hint?: string; icon?: string }) {
  return (
    <div className="card p-10 text-center animate-fade">
      <div className="grid place-items-center w-12 h-12 mx-auto rounded-2xl mb-3"
        style={{ background: 'var(--c-brand-tint)', color: 'var(--c-brand)' }}>
        <Icon name={icon} className="w-6 h-6" />
      </div>
      <div className="font-semibold" style={{ color: 'var(--c-text)' }}>{text}</div>
      {hint && <div className="text-sm mt-1" style={{ color: 'var(--c-faint)' }}>{hint}</div>}
    </div>
  )
}

export function CapexBadge({ capex }: { capex?: unknown }) {
  const v = String(capex ?? 'med').toLowerCase()
  // порядок затрат на внедрение по категории CAPEX (инженерная оценка для передела)
  const map: Record<string, [string, Tone]> = {
    low: ['внедрение до 10 млн ₽', 'ok'],
    med: ['внедрение 10–100 млн ₽', 'default'],
    medium: ['внедрение 10–100 млн ₽', 'default'],
    high: ['внедрение от 100 млн ₽', 'warn'],
  }
  const [label, tone] = map[v] ?? map.med
  return (
    <Badge tone={tone}
      title="Порядок затрат на внедрение — по категории CAPEX (низкий/средний/высокий), типовые диапазоны для обогатительного передела">
      {label}
    </Badge>
  )
}

/* -------------------------------- Модалка -------------------------------- */
export function Modal({ title, onClose, children, wide = false }: {
  title?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  // Портал в body: иначе position:fixed считается от предка с transform
  // (.animate-in/.animate-fade) — модалка «уезжает» вниз по длинной странице.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade"
      style={{ background: 'rgba(10,14,22,.5)', backdropFilter: 'blur(2px)' }} onClick={onClose}>
      <div className={`card animate-in w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} max-h-[82vh] flex flex-col`}
        style={{ boxShadow: 'var(--shadow-pop)' }} onClick={e => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b" style={{ borderColor: 'var(--c-line)' }}>
          <div className="font-bold text-sm flex-1 min-w-0">{title}</div>
          <button className="btn btn-ghost !px-2 shrink-0" onClick={onClose} aria-label="Закрыть"><Icon name="x" /></button>
        </header>
        <div className="overflow-auto p-4">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

/** Склейка «сырых» переводов строк из PDF-экстракции для читаемого отображения:
 * одиночный \n посреди предложения -> пробел; границы предложений, списки и
 * заголовки сохраняются. Только для показа — индекс и цитаты не трогаем. */
export function reflowPdfText(text: string): string {
  return text.split(/\n{2,}/).map(par => {
    let acc = ''
    for (const raw of par.split('\n')) {
      const line = raw.trim()
      if (!line) continue
      if (!acc) { acc = line; continue }
      const sentenceEnd = /[.!?:…]["»)\]]?$/.test(acc)
      const startsList = /^([-•–—]\s|\d+[.)]\s|[а-яa-z]\)\s)/i.test(line)
      const startsLower = /^[а-яёa-z]/.test(line)
      if ((sentenceEnd && !startsLower) || startsList) acc += '\n' + line
      else acc += ' ' + line
    }
    return acc
  }).filter(Boolean).join('\n\n')
}

/** Модалка источника цитаты: «Текст» — фрагмент с подсветкой цитаты,
 * «Исходник» — PDF на странице цитаты. Стрелками ← → листаются соседние
 * фрагменты документа — контекст читается дальше границ чанка. */
export function ChunkModal({ chunkId, quote, onClose }:
  { chunkId: string; quote?: string; onClose: () => void }) {
  const [curId, setCurId] = useState(chunkId)
  const [chunk, setChunk] = useState<{
    doc_id: string; text: string; source: string; page_start: number
    has_file?: boolean; lang?: string; n?: number; doc_chunks?: number
  } | null>(null)
  const [mode, setMode] = useState<'text' | 'ru' | 'file'>('text')
  const [ruText, setRuText] = useState<string | null>(null)
  const [ruBusy, setRuBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { setCurId(chunkId); setMode('text') }, [chunkId])
  useEffect(() => {
    setRuText(null); setErr('')
    api.kbChunk(curId).then(setChunk).catch(e => setErr(String(e)))
  }, [curId])

  // перевод en/zh фрагмента на русский — лениво, при первом открытии вкладки
  useEffect(() => {
    if (mode !== 'ru' || ruText !== null || ruBusy) return
    setRuBusy(true)
    api.kbTranslate([curId])
      .then(r => setRuText(r.translations[curId] ?? 'Перевод не получен.'))
      .catch(e => setErr(String(e)))
      .finally(() => setRuBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, curId])

  const hl = (text: string) => {
    // подсветка цитаты — только на исходном фрагменте, не на соседях
    if (!quote || curId !== chunkId) return text
    const probe = quote.split(' ').slice(0, 6).join(' ')
    const i = text.toLowerCase().indexOf(probe.toLowerCase())
    if (i < 0) return text
    return (<>
      {text.slice(0, i)}
      <mark style={{ background: 'var(--c-brand-tint)', color: 'var(--c-brand-strong)', borderRadius: '3px' }}>
        {text.slice(i, i + quote.length)}
      </mark>
      {text.slice(i + quote.length)}
    </>)
  }

  const isPdf = chunk?.source.toLowerCase().endsWith('.pdf')
  const foreign = chunk?.lang != null && chunk.lang !== 'ru'
  const tabs: { value: 'text' | 'ru' | 'file'; label: string }[] = [
    { value: 'text', label: foreign ? 'Оригинал' : 'Текст' },
    ...(foreign ? [{ value: 'ru' as const, label: 'По-русски' }] : []),
    ...(chunk?.has_file ? [{ value: 'file' as const, label: isPdf ? 'PDF' : 'Исходник' }] : []),
  ]

  const n = chunk?.n ?? 0
  const total = chunk?.doc_chunks ?? 1
  const goto = (delta: number) => {
    if (!chunk) return
    const next = n + delta
    if (next < 0 || next >= total) return
    setCurId(`${chunk.doc_id}:${next}`)
  }

  return (
    <Modal wide={mode === 'file'} onClose={onClose}
      title={chunk ? (
        <span className="flex items-center gap-3 min-w-0">
          <span className="truncate flex-1 min-w-0">{chunk.source}, с. {chunk.page_start}</span>
          {tabs.length > 1 &&
            <span className="shrink-0"><Segmented options={tabs} value={mode} onChange={setMode} /></span>}
        </span>
      ) : chunkId}>
      {err && <ErrorBox error={err} />}
      {mode === 'file' && chunk?.has_file ? (
        <iframe title={`Исходник: ${chunk.source}`}
          src={`/api/kb/documents/${encodeURIComponent(chunk.doc_id)}/file`
            + (isPdf ? `#page=${chunk.page_start}` : '')}
          className="w-full rounded-md bg-white"
          style={{ height: '68vh', border: '1px solid var(--c-line)' }} />
      ) : mode === 'ru' ? (
        <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--c-text)' }}>
          {ruBusy
            ? <span className="inline-flex items-center gap-2 text-faint">
                <span className="inline-block w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                Переводим…
              </span>
            : (ruText ?? '')}
          {!ruBusy && ruText && (
            <div className="text-[11px] mt-3" style={{ color: 'var(--c-faint)' }}>
              Машинный перевод — термины и числа сверяйте с оригиналом.
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--c-text)' }}>
          {chunk ? hl(reflowPdfText(chunk.text)) : 'Загрузка…'}
        </div>
      )}
      {mode !== 'file' && chunk && (
        <div className="flex items-center justify-between gap-3 mt-4 pt-3 border-t"
          style={{ borderColor: 'var(--c-line)' }}>
          <button className="btn btn-sm" disabled={n <= 0} onClick={() => goto(-1)}
            title="Предыдущий фрагмент документа">
            <Icon name="arrowRight" className="w-4 h-4 rotate-180" /> Назад
          </button>
          <span className="num text-xs" style={{ color: 'var(--c-faint)' }}>
            фрагмент {n + 1} из {total}
            {curId !== chunkId && quote && (
              <button className="ml-2 text-brand hover:underline underline-offset-2 cursor-pointer"
                onClick={() => setCurId(chunkId)}>к цитате</button>
            )}
          </span>
          <button className="btn btn-sm" disabled={n >= total - 1} onClick={() => goto(1)}
            title="Следующий фрагмент документа">
            Вперёд <Icon name="arrowRight" className="w-4 h-4" />
          </button>
        </div>
      )}
    </Modal>
  )
}
