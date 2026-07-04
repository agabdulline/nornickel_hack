import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Project } from '../types'
import { SiteHeader } from '../components/SiteHeader'
import { ProjectCard, objectLabel, projectStep } from '../components/ProjectCard'
import { EmptyBox, Icon, PageHeader, SectionLabel, Spinner, StatCard } from '../components/common'

export default function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [lineNames, setLineNames] = useState<Map<string, string>>(new Map())
  const [q, setQ] = useState('')

  useEffect(() => {
    api.projects()
      .then(list => Promise.all(list.map(p => api.project(p.id).catch(() => p))))
      .then(setProjects)
      .catch(() => setProjects([]))
    api.lines().then(ls => setLineNames(new Map(ls.map(l => [l.id, l.name])))).catch(() => {})
  }, [])

  const removeProject = async (p: Project) => {
    if (!window.confirm(
      `Удалить проект «${p.name || p.plant}»?\nОтчёт, гипотезы и дорожная карта будут удалены безвозвратно.`)) return
    try {
      await api.deleteProject(p.id)
      setProjects(prev => (prev ?? []).filter(x => x.id !== p.id))
    } catch { /* проект уже удалён/недоступен — список перечитается при заходе */ }
  }

  const list = projects ?? []
  const stats = {
    total: list.length,
    withReport: list.filter(p => p.has_report).length,
    withHyps: list.filter(p => (p.hypotheses_count ?? 0) > 0).length,
    done: list.filter(p => projectStep(p) >= 4).length,
  }
  const filtered = list.filter(p =>
    !q.trim() || `${p.name ?? ''} ${p.plant} ${p.goal ?? ''}`.toLowerCase().includes(q.trim().toLowerCase()))

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <SiteHeader />
      <main className="flex-1 min-h-0 flex flex-col max-w-7xl w-full mx-auto px-4 md:px-6 py-6 animate-fade">
        <PageHeader title="Проекты"
          subtitle="Все проекты фабрики гипотез"
          actions={<Link to="/" className="btn btn-primary"><Icon name="plus" />Новый проект</Link>} />

        {/* сводная статистика */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 shrink-0">
          <StatCard label="Всего проектов" value={stats.total} icon="doc" />
          <StatCard label="С отчётом" value={stats.withReport} icon="chart" tone="brand" />
          <StatCard label="С гипотезами" value={stats.withHyps} icon="flask" tone="ok" />
          <StatCard label="Доведены до отчёта" value={stats.done} icon="target" />
        </div>

        {/* строка списка + поиск */}
        <div className="mt-5 mb-2 flex items-center gap-3 shrink-0">
          <SectionLabel>Список · {filtered.length}</SectionLabel>
          <input className="input max-w-xs ml-auto" placeholder="Поиск по названию / цели…"
            value={q} onChange={e => setQ(e.target.value)} />
        </div>

        {/* скролл-область со списком */}
        <div className="flex-1 min-h-0 overflow-y-auto scroll-fade pr-1 pt-1 pb-4">
          {projects === null ? <Spinner />
            : filtered.length === 0
              ? <EmptyBox text="Проектов нет" hint="Создайте проект на главной" icon="doc" />
              : (
                <div className="space-y-3 stagger">
                  {filtered.map(p =>
                    <ProjectCard key={p.id} p={p} onDelete={removeProject}
                      objectName={objectLabel(p, lineNames)} />)}
                </div>
              )}
        </div>
      </main>
    </div>
  )
}
