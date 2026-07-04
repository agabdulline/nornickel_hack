import { useEffect, useState, type ReactNode } from 'react'
import {
  HashRouter, Link, NavLink, Navigate, Route, Routes, useParams,
} from 'react-router-dom'
import { api } from './api'
import type { Project } from './types'
import ChatPanel from './components/ChatPanel'
import Report from './screens/Report'
import LossMap from './screens/LossMap'
import Hypotheses from './screens/Hypotheses'
import ExportScreen from './screens/Export'
import KB from './screens/KB'
import { EmptyBox, Icon, Logo, SectionLabel, Stepper, ThemeToggle } from './components/common'

const STEPS = [
  { path: 'report', label: 'Данные', num: 1 },
  { path: 'map', label: 'Диагностика', num: 2 },
  { path: 'hypotheses', label: 'Гипотезы', num: 3 },
  { path: 'export', label: 'Отчёт', num: 4 },
]
const STEP_PATH = ['report', 'map', 'hypotheses', 'export']

/** Текущий шаг проекта (1..4) по наличию отчёта/гипотез. */
function projectStep(p: Project): number {
  return 1 + (p.has_report ? 1 : 0) + ((p.hypotheses_count ?? 0) > 0 ? 1 : 0)
}

function fmtDate(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(+d) ? iso.slice(0, 10) : d.toLocaleDateString('ru-RU')
}

/** Точки прогресса «шаг N/4». */
function StepDots({ current, total = 4 }: { current: number; total?: number }) {
  return (
    <div className="hidden sm:flex items-center gap-1 shrink-0">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className="w-2 h-2 rounded-full transition-colors"
          style={{ background: i < current ? 'var(--c-brand)' : 'var(--c-line-strong)' }} />
      ))}
    </div>
  )
}

/* Общая шапка приложения */
function TopBar({ children }: { children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b"
      style={{ background: 'color-mix(in srgb, var(--c-surface) 88%, transparent)',
        borderColor: 'var(--c-line)', backdropFilter: 'blur(8px)' }}>
      <div className="max-w-screen-2xl mx-auto px-4 h-14 flex items-center gap-4">
        {children}
      </div>
    </header>
  )
}

function ProjectLayout() {
  const { pid = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [chatOpen, setChatOpen] = useState(false)

  useEffect(() => { api.project(pid).then(setProject).catch(() => setProject(null)) }, [pid])

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar>
        <Link to="/" className="shrink-0"><Logo compact /></Link>
        <span className="text-sm truncate hidden lg:block" style={{ color: 'var(--c-muted)' }}>
          {project?.plant ?? '…'}
        </span>
        <div className="mx-auto"><Stepper pid={pid} steps={STEPS} /></div>
        <div className="flex items-center gap-1.5 shrink-0">
          <NavLink to="/kb" className="btn btn-ghost btn-sm">
            <Icon name="book" className="w-4 h-4" />
            <span className="hidden md:inline">База знаний</span>
          </NavLink>
          <ThemeToggle />
          <button className="btn btn-primary btn-sm" onClick={() => setChatOpen(v => !v)}
            title="Чат-ассистент проекта">
            <Icon name="chat" className="w-4 h-4" />
            <span className="hidden sm:inline">Ассистент</span>
          </button>
        </div>
      </TopBar>
      <main className="flex-1 max-w-screen-2xl w-full mx-auto px-4 py-5 animate-fade">
        <Routes>
          <Route path="report" element={<Report />} />
          <Route path="map" element={<LossMap />} />
          <Route path="hypotheses" element={<Hypotheses />} />
          <Route path="export" element={<ExportScreen />} />
          <Route path="*" element={<Navigate to="report" replace />} />
        </Routes>
      </main>
      {chatOpen && <ChatPanel pid={pid} onClose={() => setChatOpen(false)} />}
    </div>
  )
}

function Home() {
  const [projects, setProjects] = useState<Project[]>([])
  const [plant, setPlant] = useState('')
  const [goal, setGoal] = useState('')
  const [factory, setFactory] = useState('')   // '' = авто-определение по xlsx
  const [err, setErr] = useState('')

  // список + обогащение прогрессом (has_report / hypotheses_count) для «шаг N/4»
  const load = async () => {
    try {
      const list = await api.projects()
      const full = await Promise.all(list.map(p => api.project(p.id).catch(() => p)))
      setProjects(full)
    } catch (e) { setErr(String(e)) }
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    if (!plant.trim()) { setErr('Укажите фабрику / линию'); return }
    try {
      const p = await api.createProject({ plant, goal, factory: factory || undefined })
      location.hash = `#/p/${p.id}/report`
    } catch (e) { setErr(String(e)) }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar>
        <Link to="/"><Logo /></Link>
        <div className="ml-auto flex items-center gap-1.5">
          <NavLink to="/kb" className="btn btn-ghost btn-sm">
            <Icon name="book" className="w-4 h-4" />
            <span className="hidden sm:inline">База знаний</span>
          </NavLink>
          <ThemeToggle />
        </div>
      </TopBar>

      <main className="max-w-7xl mx-auto w-full px-4 md:px-6 py-8 animate-fade">
        {/* заголовок */}
        <div className="flex items-start justify-between gap-4 flex-wrap mb-7">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.16em] mb-1.5"
              style={{ color: 'var(--c-brand)' }}>
              Обогащение · снижение потерь металлов
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight">Проекты</h1>
          </div>
          <div className="badge badge-outline num mt-1.5">технолог НОФ · научн. сотрудник НИИ</div>
        </div>

        <div className="grid lg:grid-cols-3 gap-5 items-start">
          {/* новый проект */}
          <div className="card p-5 lg:sticky lg:top-20">
            <div className="flex items-center gap-2.5 mb-4">
              <span className="grid place-items-center w-9 h-9 rounded-xl shrink-0 text-white"
                style={{ background: 'var(--c-brand)' }}>
                <Icon name="plus" className="w-4 h-4" strokeWidth={2.6} />
              </span>
              <h2 className="font-bold text-lg">Новый проект</h2>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="field-label">Фабрика / линия</span>
                <input className="input mt-1.5" placeholder="напр. НОФ · линия 2 · Cu–Ni"
                  value={plant} onChange={e => setPlant(e.target.value)} />
              </label>
              <label className="block">
                <span className="field-label">Цель</span>
                <input className="input mt-1.5" placeholder="напр. снизить потери Ni на 1.5 п.п."
                  value={goal} onChange={e => setGoal(e.target.value)} />
              </label>
              <label className="block">
                <span className="field-label">Схема фабрики (регламент)</span>
                <select className="select mt-1.5" value={factory} onChange={e => setFactory(e.target.value)}>
                  <option value="">Авто — по загруженному отчёту</option>
                  <option value="НОФ">НОФ (Норильская)</option>
                  <option value="ТОФ">ТОФ (Талнахская)</option>
                  <option value="КГМК">КГМК (Кольская)</option>
                </select>
              </label>
            </div>
            <button className="btn btn-primary btn-lg w-full mt-4" onClick={create}>
              Создать проект <Icon name="arrowRight" className="w-4 h-4" />
            </button>
            {err && <div className="text-sm mt-2" style={{ color: 'var(--c-danger)' }}>{err}</div>}
          </div>

          {/* существующие проекты */}
          <div className="lg:col-span-2">
            <SectionLabel>Существующие проекты</SectionLabel>
            {projects.length === 0
              ? <EmptyBox text="Пока нет проектов" hint="Создайте первый проект слева" icon="doc" />
              : (
                <div className="space-y-3 stagger">
                  {projects.map(p => {
                    const step = projectStep(p)
                    return (
                      <Link key={p.id} to={`/p/${p.id}/${STEP_PATH[step - 1]}`}
                        className="card hover-lift px-5 py-4 flex items-center gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="font-bold truncate">{p.plant}</div>
                          <div className="text-sm truncate mt-0.5" style={{ color: 'var(--c-muted)' }}>
                            {p.goal ? `Цель: ${p.goal}` : '—'}
                          </div>
                        </div>
                        <StepDots current={step} />
                        <div className="text-right shrink-0">
                          <div className="num text-xs" style={{ color: 'var(--c-faint)' }}>
                            {fmtDate(p.created_at)}
                          </div>
                          <div className="text-xs font-bold mt-1 flex items-center gap-1 justify-end"
                            style={{ color: 'var(--c-brand)' }}>
                            шаг {step}/4 <Icon name="arrowRight" className="w-3.5 h-3.5" />
                          </div>
                        </div>
                      </Link>
                    )
                  })}
                </div>
              )}
          </div>
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/kb" element={<KBWrap />} />
        <Route path="/p/:pid/*" element={<ProjectLayout />} />
      </Routes>
    </HashRouter>
  )
}

function KBWrap() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopBar>
        <Link to="/"><Logo /></Link>
        <span className="text-sm" style={{ color: 'var(--c-muted)' }}>База знаний</span>
        <div className="ml-auto"><ThemeToggle /></div>
      </TopBar>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5 animate-fade">
        <KB />
      </main>
    </div>
  )
}
