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
import { EmptyBox, Icon, Logo, Panel, Stepper, ThemeToggle } from './components/common'

const STEPS = [
  { path: 'report', label: 'Данные', num: 1 },
  { path: 'map', label: 'Диагностика', num: 2 },
  { path: 'hypotheses', label: 'Гипотезы', num: 3 },
  { path: 'export', label: 'Отчёт', num: 4 },
]

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
  const [plant, setPlant] = useState('НОФ · вкрапленные руды')
  const [goal, setGoal] = useState('Снижение потерь Ni и Cu в отвальных хвостах')
  const [factory, setFactory] = useState('')   // '' = авто-определение по xlsx
  const [err, setErr] = useState('')

  const load = () => api.projects().then(setProjects).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const create = async () => {
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

      {/* герой */}
      <div className="border-b" style={{ borderColor: 'var(--c-line)',
        background: 'linear-gradient(180deg, var(--c-brand-tint), transparent)' }}>
        <div className="max-w-5xl mx-auto px-4 py-10">
          <div className="badge badge-brand mb-3">
            <Icon name="factory" className="w-3.5 h-3.5" /> Обогащение · снижение потерь металлов
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight"
            style={{ color: 'var(--c-brand-strong)' }}>
            Фабрика гипотез
          </h1>
          <p className="mt-2 max-w-2xl text-[15px]" style={{ color: 'var(--c-muted)' }}>
            От отчёта института по хвостам — к ранжированным проверяемым гипотезам снижения
            потерь Ni и&nbsp;Cu: с механизмом, цитатами из литературы, оценкой эффекта в тоннах
            и деньгах, рисками и дорожной картой проверки.
          </p>
        </div>
      </div>

      <main className="max-w-5xl mx-auto w-full px-4 py-8 space-y-6">
        <Panel title="Новый проект"
          subtitle="Создайте проект, затем загрузите Excel-отчёт по хвостам">
          <div className="grid md:grid-cols-2 gap-4">
            <label className="block">
              <span className="field-label">Фабрика / линия</span>
              <input className="input mt-1.5" value={plant} onChange={e => setPlant(e.target.value)} />
            </label>
            <label className="block">
              <span className="field-label">Цель</span>
              <input className="input mt-1.5" value={goal} onChange={e => setGoal(e.target.value)} />
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
            <div className="flex items-end">
              <button className="btn w-full" disabled title="В этой версии — предзагруженные схемы">
                <Icon name="upload" className="w-4 h-4" /> Загрузить свой регламент
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3 mt-4">
            <button className="btn btn-primary btn-lg" onClick={create}>
              Создать проект <Icon name="arrowRight" className="w-4 h-4" />
            </button>
            {err && <div className="text-sm" style={{ color: 'var(--c-danger)' }}>{err}</div>}
          </div>
        </Panel>

        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="font-bold text-lg">Проекты</h2>
            <span className="badge">{projects.length}</span>
          </div>
          {projects.length === 0
            ? <EmptyBox text="Пока нет проектов" hint="Создайте первый проект выше" icon="doc" />
            : (
              <div className="grid sm:grid-cols-2 gap-3 stagger">
                {projects.map(p => (
                  <Link key={p.id} to={`/p/${p.id}/report`}
                    className="card hover-lift p-4 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-semibold truncate">{p.plant}</div>
                      <div className="text-xs truncate mt-0.5" style={{ color: 'var(--c-faint)' }}>{p.goal}</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="num text-xs" style={{ color: 'var(--c-faint)' }}>
                        {p.created_at?.slice(0, 10)}
                      </span>
                      <Icon name="arrowRight" className="w-4 h-4" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
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
