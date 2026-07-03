import { useEffect, useState } from 'react'
import {
  HashRouter, Link, NavLink, Navigate, Route, Routes, useParams,
} from 'react-router-dom'
import { api } from './api'
import type { Line, Project, ProjectConstraints } from './types'
import ChatPanel from './components/ChatPanel'
import { EquipmentEditor, LineCombobox, MaterialsEditor } from './components/lines'
import Report from './screens/Report'
import LossMap from './screens/LossMap'
import Hypotheses from './screens/Hypotheses'
import ExportScreen from './screens/Export'
import KB from './screens/KB'

const REGULATORY_OPTIONS: { key: string; label: string }[] = [
  { key: 'ecology', label: 'Экологические нормы' },
  { key: 'industrial_safety', label: 'Промышленная безопасность' },
  { key: 'sector_standard', label: 'Отраслевой стандарт' },
]

function emptyConstraints(): ProjectConstraints {
  return { equipment: [], materials: [], regulatory: [], regulatory_notes: '' }
}

/** Название проекта по умолчанию: "{линия} · QN YYYY". */
function defaultProjectName(lineName: string): string {
  const d = new Date()
  const q = Math.floor(d.getMonth() / 3) + 1
  return `${lineName} · Q${q} ${d.getFullYear()}`
}

/** Блок «Ограничения»: оборудование и сырьё линии (write-through), нормативка. */
function ConstraintsSection({ line, value, onChange }: {
  line: Line; value: ProjectConstraints
  onChange: (v: ProjectConstraints) => void
}) {
  useEffect(() => {
    let live = true
    Promise.all([
      line.type === 'lab' ? Promise.resolve([]) : api.equipmentForLine(line.id),
      api.lineMaterials(line.id),
    ]).then(([equipment, materials]) => {
      if (!live) return
      onChange({ ...value, equipment, materials })
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }).catch(() => {})
    return () => { live = false }
    // подтягиваем каталог только при смене линии — value намеренно не в зависимостях
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [line.id, line.type])

  const toggleRegulatory = (key: string) => {
    const has = value.regulatory.includes(key)
    onChange({ ...value, regulatory: has ? value.regulatory.filter(k => k !== key) : [...value.regulatory, key] })
  }

  return (
    <div className="space-y-3 pt-3 border-t border-slate-100">
      <h3 className="font-semibold text-sm text-slate-700">Ограничения</h3>

      {line.type !== 'lab' && (
        <EquipmentEditor lineId={line.id} value={value.equipment}
          onChange={equipment => onChange({ ...value, equipment })} />
      )}

      <MaterialsEditor lineId={line.id} value={value.materials}
        onChange={materials => onChange({ ...value, materials })} />

      {/* нормативка */}
      <div>
        <div className="text-xs text-slate-500 mb-1">Нормативные требования</div>
        <div className="flex flex-wrap gap-3 mb-2">
          {REGULATORY_OPTIONS.map(o => (
            <label key={o.key} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={value.regulatory.includes(o.key)}
                onChange={() => toggleRegulatory(o.key)} />
              {o.label}
            </label>
          ))}
        </div>
        <input className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm placeholder:text-slate-400"
          placeholder="уточнения…" value={value.regulatory_notes}
          onChange={e => onChange({ ...value, regulatory_notes: e.target.value })} />
      </div>
    </div>
  )
}

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
          <span className="text-sm text-slate-500 truncate">{(project?.name || project?.plant) ?? '…'}</span>
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
  const [name, setName] = useState('')
  const [line, setLine] = useState<Line | null>(null)
  const [goal, setGoal] = useState('Снижение потерь Ni и Cu в отвальных хвостах')
  const [constraints, setConstraints] = useState<ProjectConstraints>(emptyConstraints())
  const [err, setErr] = useState('')

  const load = () => api.projects().then(setProjects).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const selectLine = (l: Line) => {
    setLine(l)
    setConstraints(emptyConstraints())
  }

  const create = async () => {
    if (!line) { setErr('Выберите фабрику/линию'); return }
    try {
      const finalName = name.trim() || defaultProjectName(line.name)
      const p = await api.createProject({
        plant: line.id, name: finalName, goal, project_constraints: constraints,
      })
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
            <label className="text-sm">Название проекта
              <input className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 placeholder:text-slate-400"
                placeholder={line ? defaultProjectName(line.name) : 'необязательно — подставится автоматически'}
                value={name} onChange={e => setName(e.target.value)} />
            </label>
            <label className="text-sm">Фабрика / линия
              <LineCombobox value={line} onSelect={selectLine} />
            </label>
          </div>
          <label className="text-sm block">Цель
            <input className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
              value={goal} onChange={e => setGoal(e.target.value)} />
          </label>

          {line && (
            <ConstraintsSection line={line} value={constraints} onChange={setConstraints} />
          )}

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
                  <div className="font-medium">{p.name || p.plant}</div>
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
