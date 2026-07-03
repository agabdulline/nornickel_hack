import { useEffect, useState } from 'react'
import {
  HashRouter, Link, NavLink, Navigate, Route, Routes, useParams,
} from 'react-router-dom'
import { api } from './api'
import type { Equipment, Project, ProjectConstraints } from './types'
import ChatPanel from './components/ChatPanel'
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
  return {
    equipment: [], raw_materials: [], budget_amount: null, budget_currency: 'RUB',
    regulatory: [], regulatory_notes: '',
  }
}

/** Блок «Ограничения»: оборудование линии (авто + ручное), сырьё, бюджет, нормативка. */
function ConstraintsSection({ plant, value, onChange }: {
  plant: string; value: ProjectConstraints
  onChange: (v: ProjectConstraints) => void
}) {
  const [catalog, setCatalog] = useState<Equipment[]>([])
  const [rawInput, setRawInput] = useState('')
  const [manualName, setManualName] = useState('')
  const [manualPosition, setManualPosition] = useState('')
  const [manualCategory, setManualCategory] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    if (!plant.trim()) { setCatalog([]); return }
    api.equipmentForLine(plant.trim()).then(eq => {
      if (!live) return
      setCatalog(eq)
      onChange({ ...value, equipment: eq })
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }).catch(() => { if (live) setCatalog([]) })
    return () => { live = false }
    // подтягиваем каталог только при смене линии — value намеренно не в зависимостях
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plant])

  const addManualEquipment = async () => {
    if (!manualName.trim()) return
    setBusy(true)
    try {
      const eq = await api.addEquipment({
        line_id: plant.trim(), name: manualName.trim(),
        position: manualPosition.trim(), category: manualCategory.trim(),
      })
      const next = [...catalog, eq]
      setCatalog(next)
      onChange({ ...value, equipment: next })
      setManualName(''); setManualPosition(''); setManualCategory('')
    } finally { setBusy(false) }
  }

  const addRawMaterial = () => {
    const v = rawInput.trim()
    if (!v || value.raw_materials.includes(v)) return
    onChange({ ...value, raw_materials: [...value.raw_materials, v] })
    setRawInput('')
  }

  const toggleRegulatory = (key: string) => {
    const has = value.regulatory.includes(key)
    onChange({ ...value, regulatory: has ? value.regulatory.filter(k => k !== key) : [...value.regulatory, key] })
  }

  return (
    <div className="space-y-3 pt-3 border-t border-slate-100">
      <h3 className="font-semibold text-sm text-slate-700">Ограничения</h3>

      {/* оборудование линии */}
      <div>
        <div className="text-xs text-slate-500 mb-1">Оборудование линии</div>
        {catalog.length === 0 && (
          <div className="text-sm text-slate-400 mb-1">
            {plant.trim() ? 'На этой линии оборудование ещё не заведено.' : 'Укажите линию выше.'}
          </div>
        )}
        {catalog.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {catalog.map(e => (
              <span key={e.id} className="badge bg-slate-100 text-slate-700">
                {e.name}{e.position && ` (${e.position})`}
              </span>
            ))}
          </div>
        )}
        <div className="flex gap-1.5">
          <input className="flex-1 border border-slate-300 rounded px-2 py-1 text-sm"
            placeholder="добавить единицу оборудования…"
            value={manualName} onChange={e => setManualName(e.target.value)} />
          <input className="w-24 border border-slate-300 rounded px-2 py-1 text-sm"
            placeholder="позиция" value={manualPosition} onChange={e => setManualPosition(e.target.value)} />
          <input className="w-32 border border-slate-300 rounded px-2 py-1 text-sm"
            placeholder="категория" value={manualCategory} onChange={e => setManualCategory(e.target.value)} />
          <button type="button" className="btn" disabled={busy || !manualName.trim()}
            onClick={addManualEquipment}>+ Добавить</button>
        </div>
      </div>

      {/* сырьё */}
      <div>
        <div className="text-xs text-slate-500 mb-1">Сырьё</div>
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {value.raw_materials.map(m => (
            <span key={m} className="badge bg-teal-50 text-teal-800">
              {m}
              <button type="button" className="ml-1 text-teal-500 hover:text-teal-800"
                onClick={() => onChange({ ...value, raw_materials: value.raw_materials.filter(x => x !== m) })}>
                ✕
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-1.5">
          <input className="flex-1 border border-slate-300 rounded px-2 py-1 text-sm"
            placeholder="напр.: вкрапленная руда — Enter, чтобы добавить"
            value={rawInput} onChange={e => setRawInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addRawMaterial() } }} />
          <button type="button" className="btn" onClick={addRawMaterial}>+ Добавить</button>
        </div>
      </div>

      {/* бюджет */}
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm">Бюджет (необязательно)
          <input type="number" min={0} className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
            value={value.budget_amount ?? ''}
            onChange={e => onChange({ ...value, budget_amount: e.target.value === '' ? null : Number(e.target.value) })} />
        </label>
        <label className="text-sm">Валюта
          <select className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
            value={value.budget_currency}
            onChange={e => onChange({ ...value, budget_currency: e.target.value })}>
            <option value="RUB">RUB</option>
            <option value="USD">USD</option>
          </select>
        </label>
      </div>

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
        <input className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm"
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
  const [constraints, setConstraints] = useState<ProjectConstraints>(emptyConstraints())
  const [err, setErr] = useState('')

  const load = () => api.projects().then(setProjects).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const create = async () => {
    try {
      const p = await api.createProject({ plant, goal, project_constraints: constraints })
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

          {plant.trim() && (
            <ConstraintsSection plant={plant} value={constraints} onChange={setConstraints} />
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
