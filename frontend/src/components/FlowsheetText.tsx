import { useEffect, useState } from 'react'
import { api } from '../api'
import type { FlowsheetData, FlowsheetNode } from '../types'
import { Icon, SectionLabel } from './common'

const TYPE_ORDER = ['crushing', 'grinding', 'classification', 'flotation', 'thickening',
  'magnetic', 'gravity']
const TYPE_LABEL: Record<string, string> = {
  crushing: 'Дробление', grinding: 'Измельчение', classification: 'Классификация',
  flotation: 'Флотация', thickening: 'Сгущение', magnetic: 'Магнитная', gravity: 'Гравитация',
}

/** Фабрика по имени линии — тот же принцип, что detect_factory на бэке. */
export function factoryOfLine(name: string): string | null {
  const n = name.toLowerCase()
  if (n.includes('ноф')) return 'НОФ'
  if (n.includes('тоф')) return 'ТОФ'
  if (n.includes('кгмк')) return 'КГМК'
  return null
}

const regime = (n: FlowsheetNode) => {
  const bits: string[] = []
  if (n.t_min != null) bits.push(`t=${n.t_min}′`)
  if (n.pct_solids != null) bits.push(`${n.pct_solids}% тв`)
  for (const [r, v] of Object.entries(n.reagents ?? {})) bits.push(`${r} ${v} г/т`)
  return bits.join(' · ')
}

/** Текстовая схема фабрики в карточке линии: свёрнута по умолчанию,
 * раскрывается кликом — переделы списком, узлы с режимами, ▼ хвосты. */
export default function FlowsheetText({ lineName }: { lineName: string }) {
  const factory = factoryOfLine(lineName)
  const [open, setOpen] = useState(false)
  const [fs, setFs] = useState<FlowsheetData | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'none'>('idle')

  useEffect(() => { setOpen(false); setFs(null); setState('idle') }, [lineName])
  useEffect(() => {
    if (!open || fs || state === 'loading' || !factory) return
    setState('loading')
    api.factoryFlowsheet(factory)
      .then(r => { setFs(r.flowsheet); setState('idle') })
      .catch(() => setState('none'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!factory) return null

  const tails = new Set((fs?.streams ?? []).filter(s => s.kind === 'tails').map(s => s.from))
  const groups = fs
    ? TYPE_ORDER.map(t => ({ type: t, nodes: fs.nodes.filter(n => n.type === t) }))
        .filter(g => g.nodes.length > 0)
    : []

  return (
    <div>
      <button type="button"
        className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted hover:text-brand cursor-pointer"
        title={open ? 'Свернуть схему' : `Показать оцифрованную схему фабрики ${factory}`}
        onClick={() => setOpen(v => !v)}>
        <Icon name="arrowRight" strokeWidth={2.5}
          className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
        Схема фабрики ({factory})
        {!open && <span className="normal-case font-normal text-faint">— показать</span>}
      </button>

      {open && (
        <div className="mt-2 animate-in">
          {state === 'loading' && <div className="text-sm text-faint">Загружаю схему…</div>}
          {state === 'none' && (
            <div className="text-sm text-faint">
              Схема этой фабрики не оцифрована — доступны только исходные
              изображения в разделе «Схемы фабрик» ниже.
            </div>
          )}
          {fs && (
            <div className="space-y-2.5 text-sm border-l-2 border-line pl-3">
              {groups.map(g => (
                <div key={g.type}>
                  <SectionLabel>{TYPE_LABEL[g.type]}</SectionLabel>
                  <ul className="space-y-1">
                    {g.nodes.map(n => (
                      <li key={n.id}>
                        <span className="font-medium">{n.name}</span>
                        {regime(n) && (
                          <span className="num text-xs ml-2" style={{ color: 'var(--c-muted)' }}>
                            {regime(n)}
                          </span>
                        )}
                        {tails.has(n.id) && (
                          <span className="text-xs ml-2 text-danger">▼ хвосты</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
