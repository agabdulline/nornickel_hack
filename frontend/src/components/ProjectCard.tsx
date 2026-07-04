import { Link } from 'react-router-dom'
import type { Project } from '../types'
import { Icon } from './common'

export const STEP_PATH = ['report', 'map', 'hypotheses', 'export']

/** Текущий шаг проекта (1..4) по наличию отчёта/гипотез. */
export function projectStep(p: Project): number {
  return 1 + (p.has_report ? 1 : 0) + ((p.hypotheses_count ?? 0) > 0 ? 1 : 0)
}

export function fmtDate(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(+d) ? iso.slice(0, 10) : d.toLocaleDateString('ru-RU')
}

/** Точки прогресса «шаг N/4». */
export function StepDots({ current, total = 4 }: { current: number; total?: number }) {
  return (
    <div className="hidden sm:flex items-center gap-1 shrink-0">
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className="w-2 h-2 rounded-full transition-colors"
          style={{ background: i < current ? 'var(--c-brand)' : 'var(--c-line-strong)' }} />
      ))}
    </div>
  )
}

/** Карточка проекта в списке (главная + страница «Проекты»).
 * `onDelete` включает кнопку удаления; клик по ней не открывает проект. */
export function ProjectCard({ p, onDelete }: { p: Project; onDelete?: (p: Project) => void }) {
  const step = projectStep(p)
  return (
    <Link to={`/p/${p.id}/${STEP_PATH[step - 1]}`}
      className="card hover-lift px-5 py-4 flex items-center gap-4">
      <div className="min-w-0 flex-1">
        <div className="font-bold truncate">{p.name || p.plant}</div>
        <div className="text-sm truncate mt-0.5" style={{ color: 'var(--c-muted)' }}>
          {p.goal ? `Цель: ${p.goal}` : '—'}
        </div>
      </div>
      <StepDots current={step} />
      <div className="text-right shrink-0">
        <div className="num text-xs" style={{ color: 'var(--c-faint)' }}>{fmtDate(p.created_at)}</div>
        <div className="text-xs font-bold mt-1 flex items-center gap-1 justify-end"
          style={{ color: 'var(--c-brand)' }}>
          шаг {step}/4 <Icon name="arrowRight" className="w-3.5 h-3.5" />
        </div>
      </div>
      {onDelete && (
        <button type="button" title="Удалить проект" aria-label="Удалить проект"
          className="shrink-0 grid place-items-center w-8 h-8 rounded-lg text-faint
            hover:text-danger hover:bg-danger-tint transition-colors"
          onClick={e => { e.preventDefault(); e.stopPropagation(); onDelete(p) }}>
          <Icon name="trash" className="w-4 h-4" />
        </button>
      )}
    </Link>
  )
}
