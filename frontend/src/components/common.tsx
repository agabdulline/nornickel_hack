import { useEffect, useState, type ReactNode } from 'react'
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
      <img src="/logo.png" alt="Фабрика гипотез" className="h-8 w-auto shrink-0" />
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
      <span className="inline-block w-6 h-6 rounded-full border-[2.5px] animate-spin"
        style={{ borderColor: 'var(--c-line-strong)', borderTopColor: 'var(--c-brand)' }} />
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
  const map: Record<string, [string, Tone]> = {
    low: ['CAPEX низкий', 'ok'], med: ['CAPEX средний', 'default'],
    medium: ['CAPEX средний', 'default'], high: ['CAPEX высокий', 'warn'],
  }
  const [label, tone] = map[v] ?? map.med
  return <Badge tone={tone}>{label}</Badge>
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
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade"
      style={{ background: 'rgba(10,14,22,.5)', backdropFilter: 'blur(2px)' }} onClick={onClose}>
      <div className={`card animate-in w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} max-h-[82vh] flex flex-col`}
        style={{ boxShadow: 'var(--shadow-pop)' }} onClick={e => e.stopPropagation()}>
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b" style={{ borderColor: 'var(--c-line)' }}>
          <div className="font-bold text-sm truncate">{title}</div>
          <button className="btn btn-ghost !px-2" onClick={onClose} aria-label="Закрыть"><Icon name="x" /></button>
        </header>
        <div className="overflow-auto p-4">{children}</div>
      </div>
    </div>
  )
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
      <mark style={{ background: 'var(--c-brand-tint)', color: 'var(--c-brand-strong)', borderRadius: '3px' }}>
        {text.slice(i, i + quote.length)}
      </mark>
      {text.slice(i + quote.length)}
    </>)
  }

  return (
    <Modal title={chunk ? `${chunk.source}, с. ${chunk.page_start}` : chunkId} onClose={onClose}>
      {err && <ErrorBox error={err} />}
      <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--c-text)' }}>
        {chunk ? hl(chunk.text) : 'Загрузка…'}
      </div>
    </Modal>
  )
}
