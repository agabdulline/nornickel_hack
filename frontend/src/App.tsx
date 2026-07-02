import { useEffect, useState } from 'react'
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

const STEPS = [
  { path: 'report', label: '1 · Данные' },
  { path: 'map', label: '2 · Диагностика' },
  { path: 'hypotheses', label: '3 · Гипотезы' },
  { path: 'export', label: '4 · Отчёт' },
]

function ProjectLayout() {
  const { pid = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [chatOpen, setChatOpen] = useState(false)

  useEffect(() => { api.project(pid).then(setProject).catch(() => setProject(null)) }, [pid])

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-screen-2xl mx-auto px-4 h-12 flex items-center gap-6">
          <Link to="/" className="font-bold text-teal-800 whitespace-nowrap">
            ⚙ Фабрика гипотез
          </Link>
          <span className="text-sm text-slate-500 truncate">{project?.plant ?? '…'}</span>
          <nav className="flex gap-1 ml-4">
            {STEPS.map(s => (
              <NavLink key={s.path} to={`/p/${pid}/${s.path}`}
                className={({ isActive }) =>
                  `px-3 py-1 rounded text-sm ${isActive
                    ? 'bg-teal-700 text-white'
                    : 'text-slate-600 hover:bg-slate-100'}`}>
                {s.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <NavLink to="/kb" className="px-3 py-1 rounded text-sm text-slate-600 hover:bg-slate-100">
              База знаний
            </NavLink>
            <button className="btn" onClick={() => setChatOpen(v => !v)}
              title="Чат-ассистент проекта">💬 Ассистент</button>
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-screen-2xl w-full mx-auto px-4 py-4">
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
  const [err, setErr] = useState('')

  const load = () => api.projects().then(setProjects).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const create = async () => {
    try {
      const p = await api.createProject({ plant, goal })
      location.hash = `#/p/${p.id}/report`
    } catch (e) { setErr(String(e)) }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-screen-lg mx-auto px-4 h-12 flex items-center justify-between">
          <span className="font-bold text-teal-800">⚙ Фабрика гипотез</span>
          <Link to="/kb" className="text-sm text-slate-600 hover:underline">База знаний</Link>
        </div>
      </header>
      <main className="max-w-screen-lg mx-auto w-full px-4 py-8 space-y-6">
        <div className="card p-4 space-y-3">
          <h2 className="font-semibold text-lg">Новый проект</h2>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">Фабрика / линия
              <input className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={plant} onChange={e => setPlant(e.target.value)} />
            </label>
            <label className="text-sm">Цель
              <input className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={goal} onChange={e => setGoal(e.target.value)} />
            </label>
          </div>
          <button className="btn btn-primary" onClick={create}>Создать проект</button>
          {err && <div className="text-sm text-red-600">{err}</div>}
        </div>

        <div className="card p-4">
          <h2 className="font-semibold text-lg mb-3">Проекты</h2>
          {projects.length === 0 && <div className="text-slate-500 text-sm">Пока пусто.</div>}
          <div className="divide-y divide-slate-100">
            {projects.map(p => (
              <Link key={p.id} to={`/p/${p.id}/report`}
                className="flex items-center justify-between py-2 hover:bg-slate-50 px-2 -mx-2 rounded">
                <div>
                  <div className="font-medium">{p.plant}</div>
                  <div className="text-xs text-slate-500">{p.goal}</div>
                </div>
                <div className="text-xs text-slate-400 num">{p.created_at?.slice(0, 10)}</div>
              </Link>
            ))}
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
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-screen-xl mx-auto px-4 h-12 flex items-center gap-4">
          <Link to="/" className="font-bold text-teal-800">⚙ Фабрика гипотез</Link>
          <span className="text-sm text-slate-500">База знаний</span>
        </div>
      </header>
      <main className="flex-1 max-w-screen-xl w-full mx-auto px-4 py-4">
        <KB />
      </main>
    </div>
  )
}
