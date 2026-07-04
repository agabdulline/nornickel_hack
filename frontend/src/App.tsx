import { useEffect, useState, type ReactNode } from 'react'
import {
  HashRouter, Link, NavLink, Navigate, Route, Routes, useParams,
} from 'react-router-dom'
import { api } from './api'
import type { Line, Project, ProjectConstraints } from './types'
import ChatPanel from './components/ChatPanel'
import { EquipmentEditor, LineCombobox, MaterialsEditor, NO_OBJECT_ID } from './components/lines'
import Report from './screens/Report'
import LossMap from './screens/LossMap'
import Hypotheses from './screens/Hypotheses'
import ExportScreen from './screens/Export'
import KB from './screens/KB'
import Projects from './screens/Projects'
import { EmptyBox, Icon, Logo, Modal, SectionLabel, Spinner, Stepper, ThemeToggle } from './components/common'
import { SiteHeader } from './components/SiteHeader'
import { ProjectCard, objectLabel } from './components/ProjectCard'

function emptyConstraints(): ProjectConstraints {
  return { equipment: [], materials: [] }
}

/** Название проекта по умолчанию: "{линия} · QN YYYY". */
function defaultProjectName(lineName: string): string {
  const d = new Date()
  const q = Math.floor(d.getMonth() / 3) + 1
  return `${lineName} · Q${q} ${d.getFullYear()}`
}

/** Блок «Ограничения»: оборудование и сырьё линии (write-through), нормативка.
 *
 * Развилка не «линия/лаборатория» — у обеих есть своё оборудование — а
 * «объект выбран vs без привязки к объекту»: во втором случае площадка ещё
 * не определена и ограничения по оборудованию/сырью не применяются вовсе. */
function ConstraintsSection({ line, value, onChange }: {
  line: Line; value: ProjectConstraints
  onChange: (v: ProjectConstraints) => void
}) {
  const noObject = line.id === NO_OBJECT_ID

  useEffect(() => {
    if (noObject) { onChange({ ...value, equipment: [], materials: [] }); return }
    let live = true
    Promise.all([api.equipmentForLine(line.id), api.lineMaterials(line.id)])
      .then(([equipment, materials]) => {
        if (!live) return
        onChange({ ...value, equipment, materials })
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }).catch(() => {})
    return () => { live = false }
    // подтягиваем каталог только при смене линии — value намеренно не в зависимостях
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [line.id, noObject])

  return (
    <div className="space-y-3 pt-3 border-t border-line">
      <SectionLabel>Ограничения</SectionLabel>

      {noObject ? (
        <div className="text-sm text-faint">
          Площадка не выбрана — ограничения по оборудованию и сырью не применяются,
          гипотезы будут теоретическими.
        </div>
      ) : (
        <>
          <EquipmentEditor lineId={line.id} value={value.equipment}
            onChange={equipment => onChange({ ...value, equipment })} />
          <MaterialsEditor lineId={line.id} value={value.materials}
            onChange={materials => onChange({ ...value, materials })} />
        </>
      )}
    </div>
  )
}

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
        <Link to="/" className="shrink-0 flex items-center"><Logo /></Link>
        {(project?.name || project?.plant) && (
          <span className="text-sm hidden lg:flex items-center gap-2 min-w-0"
            style={{ color: 'var(--c-muted)' }}>
            <span style={{ color: 'var(--c-line-strong)' }}>·</span>
            <span className="truncate">{project?.name || project?.plant}</span>
          </span>
        )}
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
          {/* абсолютный путь: относительный `to` внутри splat-роута резолвится
              от текущего URL и даёт бесконечный редирект /x/report/report/… */}
          <Route path="*" element={<Navigate to={`/p/${pid}/report`} replace />} />
        </Routes>
      </main>
      {chatOpen && <ChatPanel pid={pid} onClose={() => setChatOpen(false)} />}
    </div>
  )
}

function Home() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loadingProjects, setLoadingProjects] = useState(true)
  // id линии -> отображаемое имя: чтобы на карточке показать объект проекта
  const [lineNames, setLineNames] = useState<Map<string, string>>(new Map())
  const [name, setName] = useState('')
  const [line, setLine] = useState<Line | null>(null)
  const [goal, setGoal] = useState('Снижение потерь Ni и Cu в отвальных хвостах')
  // материалы, приложенные в модалке создания: зальются после создания проекта
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [factory, setFactory] = useState('')   // '' = авто-определение по xlsx

  const [constraints, setConstraints] = useState<ProjectConstraints>(emptyConstraints())
  const [err, setErr] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // список + обогащение прогрессом (has_report / hypotheses_count) для «шаг N/4»
  const load = async () => {
    try {
      const list = await api.projects()
      const full = await Promise.all(list.map(p => api.project(p.id).catch(() => p)))
      setProjects(full)
    } catch (e) { setErr(String(e)) }
    finally { setLoadingProjects(false) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    api.lines().then(ls => setLineNames(new Map(ls.map(l => [l.id, l.name])))).catch(() => {})
  }, [])

  const removeProject = async (p: Project) => {
    if (!window.confirm(
      `Удалить проект «${p.name || p.plant}»?\nОтчёт, гипотезы и дорожная карта будут удалены безвозвратно.`)) return
    try {
      await api.deleteProject(p.id)
      setProjects(prev => prev.filter(x => x.id !== p.id))
    } catch (e) { setErr(String(e)) }
  }

  const selectLine = (l: Line) => {
    setLine(l)
    setConstraints(emptyConstraints())
  }

  const create = async () => {
    if (!line) { setErr('Выберите фабрику/линию'); return }
    try {
      const finalName = name.trim() || defaultProjectName(line.name)
      const p = await api.createProject({
        plant: line.id, name: finalName, goal,
        project_constraints: constraints, factory: factory || undefined,
      })
      // материалы, приложенные в модалке, заливаем сразу после создания
      // (картинки распознает Яндекс OCR; текст учитывается при генерации)
      for (const f of pendingFiles) {
        try { await api.projectFileUpload(p.id, f) } catch { /* не блокируем создание */ }
      }
      location.hash = `#/p/${p.id}/report`
    } catch (e) { setErr(String(e)) }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <SiteHeader actions={
        <button className="btn btn-primary btn-sm" onClick={() => setChatOpen(v => !v)}
          title="Ассистент — вопросы к базе знаний">
          <Icon name="chat" className="w-4 h-4" />
          <span className="hidden sm:inline">Ассистент</span>
        </button>
      } />

      <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-10 md:py-14 animate-fade">
        {/* герой */}
        <div className="text-center mb-8">
          <div className="text-[11px] font-bold uppercase tracking-[0.16em] mb-2"
            style={{ color: 'var(--c-brand)' }}>
            Обогащение · снижение потерь металлов
          </div>
          <h1 className="text-3xl md:text-5xl font-extrabold tracking-tight">Фабрика гипотез</h1>
          <p className="mt-2.5 text-[15px] max-w-2xl mx-auto" style={{ color: 'var(--c-muted)' }}>
            От отчёта института — к ранжированным проверяемым гипотезам
            снижения потерь Ni и&nbsp;Cu в хвостах, концентратах и промпродуктах.
          </p>
        </div>

        {/* горизонтальная карточка быстрого создания */}
        <div className="card p-4 md:p-5" style={{ boxShadow: 'var(--shadow-card)' }}>
          <div className="flex flex-col lg:flex-row gap-3 lg:items-end">
            <label className="block lg:flex-1 min-w-0">
              <span className="field-label">Название проекта</span>
              <input className="input mt-1.5"
                placeholder={line ? defaultProjectName(line.name) : 'напр.: НОФ · вкрапленные руды'}
                value={name} onChange={e => setName(e.target.value)} />
            </label>
            <label className="block lg:flex-1 min-w-0">
              <span className="field-label">Фабрика / линия</span>
              <LineCombobox value={line} onSelect={selectLine} allowCreate={false} />
            </label>
            <label className="block lg:flex-1 min-w-0">
              <span className="field-label">Цель</span>
              <input className="input mt-1.5" placeholder="снизить потери Ni на 1.5 п.п."
                value={goal} onChange={e => setGoal(e.target.value)} />
            </label>
            <div className="flex gap-2 shrink-0">
              <button className="btn" onClick={() => setSettingsOpen(true)}
                title="Схема фабрики и ограничения по оборудованию/сырью">
                Все настройки
              </button>
              <button className="btn btn-primary" onClick={create}>
                Создать <Icon name="arrowRight" className="w-4 h-4" />
              </button>
            </div>
          </div>
          {line && (
            <div className="text-xs mt-2.5 flex items-center gap-1.5" style={{ color: 'var(--c-faint)' }}>
              <Icon name="lock" className="w-3.5 h-3.5 shrink-0" />
              Ограничения по оборудованию и сырью линии — в «Все настройки»
            </div>
          )}
          {err && <div className="text-sm mt-2" style={{ color: 'var(--c-danger)' }}>{err}</div>}
        </div>

        {/* последние проекты */}
        <div className="mt-9">
          <div className="flex items-center gap-3 mb-3">
            <SectionLabel>Последние проекты</SectionLabel>
            <Link to="/projects" className="btn btn-ghost btn-sm ml-auto">
              Просмотреть все <Icon name="arrowRight" className="w-3.5 h-3.5" />
            </Link>
          </div>
          {loadingProjects
            ? <Spinner label="Загружаю проекты…" />
            : projects.length === 0
            ? <EmptyBox text="Пока нет проектов" hint="Создайте первый проект выше" icon="doc" />
            : (
              <div className="grid sm:grid-cols-2 gap-3 stagger">
                {projects.slice(0, 4).map(p =>
                  <ProjectCard key={p.id} p={p} onDelete={removeProject}
                    objectName={objectLabel(p, lineNames)} />)}
              </div>
            )}
        </div>
      </main>

      {settingsOpen && (
        <Modal title="Новый проект — все настройки" onClose={() => setSettingsOpen(false)}>
          <div className="space-y-3">
            <label className="block">
              <span className="field-label">Название проекта</span>
              <input className="input mt-1.5"
                placeholder={line ? defaultProjectName(line.name) : 'напр.: НОФ · вкрапленные руды · Q3 2026'}
                value={name} onChange={e => setName(e.target.value)} />
            </label>
            <label className="block">
              <span className="field-label">Фабрика / линия</span>
              <LineCombobox value={line} onSelect={selectLine} allowCreate={false} />
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
            {line && <ConstraintsSection line={line} value={constraints} onChange={setConstraints} />}

            {/* материалы проекта: зальются после создания; картинки распознает OCR */}
            <div className="block">
              <span className="field-label">Материалы (регламенты, схемы, фото, заметки)</span>
              <div className="mt-1.5 space-y-1.5">
                {pendingFiles.map((f, i) => (
                  <div key={i} className="card-2 px-3 py-1.5 flex items-center gap-2 text-sm">
                    <Icon name="doc" className="w-4 h-4 shrink-0 text-faint" />
                    <span className="flex-1 truncate">{f.name}</span>
                    <button type="button" className="shrink-0 hover:text-danger"
                      onClick={() => setPendingFiles(fs => fs.filter((_, n) => n !== i))}>
                      <Icon name="x" className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                <input type="file" multiple className="hidden" id="new-project-files"
                  accept=".png,.jpg,.jpeg,.webp,.bmp,.pdf,.txt,.md,.csv,.docx"
                  onChange={e => {
                    setPendingFiles(fs => [...fs, ...Array.from(e.target.files ?? [])])
                    e.target.value = ''
                  }} />
                <label htmlFor="new-project-files" className="btn btn-sm cursor-pointer">
                  <Icon name="upload" className="w-4 h-4" /> Прикрепить файлы
                </label>
                <div className="text-[11px]" style={{ color: 'var(--c-faint)' }}>
                  Картинки распознаёт Яндекс OCR; текст учитывается при генерации гипотез,
                  схемы показываются на диагностике.
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3 mt-4 pt-3 border-t" style={{ borderColor: 'var(--c-line)' }}>
            <button className="btn btn-primary" onClick={create}>
              Создать проект <Icon name="arrowRight" className="w-4 h-4" />
            </button>
            <button className="btn btn-ghost" onClick={() => setSettingsOpen(false)}>Отмена</button>
            {err && <span className="text-sm ml-auto" style={{ color: 'var(--c-danger)' }}>{err}</span>}
          </div>
        </Modal>
      )}
      {chatOpen && <ChatPanel onClose={() => setChatOpen(false)} />}
    </div>
  )
}

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/kb" element={<KBWrap />} />
        <Route path="/p/:pid/*" element={<ProjectLayout />} />
      </Routes>
    </HashRouter>
  )
}

function KBWrap() {
  return (
    <div className="min-h-screen flex flex-col">
      <SiteHeader />
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5 animate-fade">
        <KB />
      </main>
    </div>
  )
}
