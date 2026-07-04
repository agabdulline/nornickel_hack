import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import { HIGHLIGHT_EVENT, peekPending, useChatHighlight } from '../highlight'
import type { DiagnosticsResult, FlowsheetData, FlowsheetNode, TailingsReport } from '../types'
import {
  Badge, EmptyBox, ErrorBox, Icon, Modal, PageHeader, Panel, SectionLabel, Segmented, Spinner,
} from '../components/common'

const FORMS = ['Раскрытый Pnt/Cp', 'Закрытый Pnt/Cp', 'Примесь в пирротине',
  'Силикатная форма', 'Пирит', 'Миллерит']
const CLASSES = ['+125', '-125+71', '-71+45', '-45+20', '-20+10', '-10']
const ELEMENTS = ['Ni', 'Cu'] as const

const TYPE_ORDER = ['crushing', 'grinding', 'classification', 'flotation', 'thickening',
  'magnetic', 'gravity']
const TYPE_LABEL: Record<string, string> = {
  crushing: 'Дробление', grinding: 'Измельчение', classification: 'Классификация',
  flotation: 'Флотация', thickening: 'Сгущение', magnetic: 'Магнитная', gravity: 'Гравитация',
}

/** Исходные изображения схем/регламента, из которых оцифрован флоушит.
 * Несколько файлов — вкладками сверху, ниже рисуется только выбранный. */
function FlowsheetSources({ factory, files, onClose, initial = 0 }: {
  factory: string; files: string[]; onClose: () => void; initial?: number
}) {
  const [active, setActive] = useState(initial)
  const i = Math.min(active, files.length - 1)
  return (
    <Modal wide onClose={onClose}
      title={`Исходные схемы: ${factory} (${files.length} изобр.)`}>
      {files.length > 1 && (
        <div className="flex flex-wrap gap-1.5 mb-3 pb-3 border-b border-line">
          {files.map((name, n) => (
            <button key={name} type="button" onClick={() => setActive(n)}
              className={`chip ${n === i ? 'chip-active' : ''}`}>{name}</button>
          ))}
        </div>
      )}
      <figure>
        {files.length <= 1 && (
          <figcaption className="text-xs text-muted mb-1.5">{files[i]}</figcaption>
        )}
        <img src={`/api/flowsheet-image/${encodeURIComponent(factory)}/${i}`}
          alt={files[i]} loading="lazy"
          className="max-w-full rounded-md border border-line bg-white" />
      </figure>
    </Modal>
  )
}

/** Граф переделов из оцифрованного регламента фабрики (реальные названия операций). */
function FlowsheetGraph({ factory, fs, highlight }: {
  factory: string | null; fs: FlowsheetData; highlight: Set<string>
}) {
  const [showSources, setShowSources] = useState<number | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const digitized = fs.nodes.length > 0
  const groups = TYPE_ORDER
    .map(t => ({ type: t, nodes: fs.nodes.filter(n => n.type === t) }))
    .filter(g => g.nodes.length > 0)
  const tails = fs.streams.filter(s => s.kind === 'tails')
  const tailFrom = new Set(tails.map(s => s.from))
  const sources = fs.source_files ?? []

  const regime = (n: FlowsheetNode) => {
    const bits: string[] = []
    if (n.t_min != null) bits.push(`t=${n.t_min}′`)
    if (n.pct_solids != null) bits.push(`${n.pct_solids}% тв`)
    for (const [r, v] of Object.entries(n.reagents ?? {})) bits.push(`${r} ${v} г/т`)
    if (n.equipment_positions?.length) bits.push(`поз. ${n.equipment_positions.join(',')}`)
    return bits.join(' · ')
  }

  return (
    <Panel
      title={`Схема фабрики: ${factory}`}
      subtitle={digitized
        ? 'по оцифрованному регламенту; подсвечены переделы сработавших диагнозов'
        : 'исходные схемы из материалов кейса (граф переделов не оцифрован)'}
      bodyClass={collapsed ? 'p-0' : 'p-3'}
      actions={
        <div className="flex items-center gap-1.5 shrink-0">
          {digitized && sources.length > 0 && factory && (
            <button className="btn btn-sm !px-2" title={`Исходные схемы (${sources.length}) — изображения, с которых оцифрована схема`}
              onClick={() => setShowSources(0)}>
              <Icon name="search" className="w-4 h-4" />
              <span className="num">{sources.length}</span>
            </button>
          )}
          <button className="btn btn-sm !px-2" onClick={() => setCollapsed(v => !v)}
            aria-expanded={!collapsed} title={collapsed ? 'Развернуть схему' : 'Свернуть схему'}>
            <Icon name="arrowRight"
              className={`w-4 h-4 transition-transform duration-200 ${collapsed ? '' : 'rotate-90'}`} />
          </button>
        </div>
      }>
      {!collapsed && !digitized && factory && (
        <div className="flex flex-wrap gap-4 animate-in">
          {sources.map((name, i) => (
            <figure key={name} className="cursor-pointer group" onClick={() => setShowSources(i)}
              title="Открыть в полном размере">
              <img src={`/api/flowsheet-image/${encodeURIComponent(factory)}/${i}`} alt={name}
                loading="lazy"
                className="h-44 max-w-full rounded-md border border-line bg-white object-contain
                  transition-colors group-hover:border-brand" />
              <figcaption className="text-[11px] mt-1 text-center"
                style={{ color: 'var(--c-faint)' }}>{name}</figcaption>
            </figure>
          ))}
        </div>
      )}
      {!collapsed && digitized && (
        <div className="flex flex-col items-center gap-1.5 animate-in">
          {groups.map((g, gi) => (
            <div key={g.type} className="flex flex-col items-center gap-1.5 w-full">
              {gi > 0 && (
                <Icon name="arrowRight" className="w-4 h-4 rotate-90 opacity-25 shrink-0 text-faint" />
              )}
              <div className="card-2 p-2.5 w-full max-w-3xl">
                <div className="text-[10px] uppercase mb-1.5 text-center tracking-wide"
                  style={{ color: 'var(--c-faint)' }}>
                  {TYPE_LABEL[g.type]}
                </div>
                <div className="flex flex-wrap justify-center gap-1.5">
                  {g.nodes.map(n => (
                    <div key={n.id} title={regime(n)}
                      className={`rounded-md px-2 py-1 text-xs w-40 border ${highlight.has(n.id)
                        ? 'bg-brand-tint border-brand font-semibold'
                        : 'bg-surface border-line'}`}>
                      <div className="truncate">{n.name}</div>
                      {regime(n) && (
                        <div className="text-[10px] truncate num" style={{ color: 'var(--c-muted)' }}>
                          {regime(n)}
                        </div>
                      )}
                      {tailFrom.has(n.id) &&
                        <div className="text-[10px] text-danger">▼ хвосты</div>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {showSources !== null && factory && (
        <FlowsheetSources factory={factory} files={sources} initial={showSources}
          onClose={() => setShowSources(null)} />
      )}
    </Panel>
  )
}

/** Тепловая матрица классы×формы для одного элемента. */
function HeatTable({ el, diag }: { el: 'Ni' | 'Cu'; diag: DiagnosticsResult }) {
  const map = diag.loss_map?.[el] ?? {}
  const classes = CLASSES.filter(c => map[c])
  const maxT = Math.max(1, ...classes.flatMap(c => FORMS.map(f => map[c]?.[f]?.tonnes ?? 0)))

  return (
    <>
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr>
              <th>Класс, мкм</th>
              {FORMS.map(f => {
                const rec = map[classes[0]]?.[f]?.recoverable
                return (
                  <th key={f} className={rec === false ? 'text-faint' : ''}>
                    {rec === false && '🔒 '}{f}
                  </th>
                )
              })}
              <th className="text-right">Итого класс</th>
            </tr>
          </thead>
          <tbody>
            {classes.map(c => {
              const rowT = FORMS.reduce((s, f) => s + (map[c]?.[f]?.tonnes ?? 0), 0)
              return (
                <tr key={c}>
                  <td className="font-semibold num">{c}</td>
                  {FORMS.map(f => {
                    const cell = map[c]?.[f]
                    if (!cell) return <td key={f} className="text-faint">—</td>
                    const alpha = Math.pow((cell.tonnes ?? 0) / maxT, 0.6)
                    const bg = cell.recoverable
                      ? `rgba(var(--heat), ${(0.06 + alpha * 0.55).toFixed(3)})`
                      : `rgba(var(--heat-inert), ${(0.04 + alpha * 0.28).toFixed(3)})`
                    return (
                      <td key={f} data-hl={`cell:${c}/${f}/${el}`}
                        title={`${c} / ${f} / ${el}: ${fmt.t(cell.tonnes)} т` +
                        (cell.share_pct != null ? ` (${fmt.pct(cell.share_pct)})` : '') +
                        (cell.recoverable ? ' · извлекаемо' : ' · НЕизвлекаемо') +
                        (cell.provenance !== 'measured' ? ` · ${cell.provenance}` : '')}
                        className={`num text-right ${!cell.recoverable ? 'text-muted' : ''} ` +
                          (cell.provenance !== 'measured' ? 'recovered-cell' : '')}
                        style={{ background: cell.provenance === 'measured' ? bg : undefined }}>
                        {fmt.t(cell.tonnes, 0)}
                      </td>
                    )
                  })}
                  <td className="num text-right font-semibold">{fmt.t(rowT, 0)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="text-xs mt-2" style={{ color: 'var(--c-faint)' }}>
        интенсивность = тонны потерь · 🔒 приглушённые колонки — неизвлекаемые формы ·
        янтарный пунктир — значения для проверки
      </div>
    </>
  )
}

export default function LossMap() {
  const { pid = '' } = useParams()
  const nav = useNavigate()
  const [reports, setReports] = useState<TailingsReport[] | null>(null)
  const [tailType, setTailType] = useState<string>('')
  const [diag, setDiag] = useState<DiagnosticsResult | null>(null)
  const [el, setEl] = useState<'Ni' | 'Cu'>('Ni')
  const [err, setErr] = useState('')
  const [openRule, setOpenRule] = useState<string | null>(null)
  const [fsInfo, setFsInfo] = useState<{ factory: string | null; flowsheet: FlowsheetData | null } | null>(null)

  useEffect(() => {
    let live = true
    api.flowsheet(pid)
      .then(v => { if (live) setFsInfo(v) })
      .catch(() => { if (live) setFsInfo(null) })
    return () => { live = false }
  }, [pid])

  // Смена проекта переиспользует этот же компонент (роут /p/:pid/map не меняется),
  // поэтому вручную сбрасываем ошибку и данные прошлого проекта — иначе «залипают»
  // (напр. ошибка «отчёт не загружен» остаётся, хотя новый проект загрузился).
  // live-флаг отбрасывает ответы устаревшего запроса при быстром переключении.
  useEffect(() => {
    let live = true
    setErr(''); setReports(null); setDiag(null); setTailType('')
    api.report(pid)
      .then(r => { if (!live) return; setReports(r.reports); setTailType(r.reports[0]?.tail_type ?? '') })
      .catch(e => { if (live) setErr(String(e)) })
    return () => { live = false }
  }, [pid])

  useEffect(() => {
    if (!tailType) return
    let live = true
    setErr('')
    api.diagnostics(pid, tailType)
      .then(d => { if (live) setDiag(d) })
      .catch(e => { if (live) setErr(String(e)) })
    return () => { live = false }
  }, [pid, tailType])

  const report = useMemo(() =>
    reports?.find(r => r.tail_type === tailType) ?? reports?.[0], [reports, tailType])

  // подсветка цели, на которую указал ассистент; если цель — ячейка другого
  // элемента (…/Cu при открытом Ni), сперва переключаем вкладку
  useEffect(() => {
    const sync = () => {
      const t = peekPending()
      const m = t?.type === 'cell' ? t.id.match(/\/(Ni|Cu)$/) : null
      if (m) setEl(m[1] as 'Ni' | 'Cu')
    }
    sync()
    window.addEventListener(HIGHLIGHT_EVENT, sync)
    return () => window.removeEventListener(HIGHLIGHT_EVENT, sync)
  }, [])
  useChatHighlight(!!diag, [el])

  if (err) return <ErrorBox error={err.includes('не загружен') ?
    'Отчёт ещё не загружен — начните с шага «1 · Данные».' : err} />
  if (!report || !diag) return <Spinner />

  const diagnoses = diag.diagnoses.filter(d => d.element === el)
  const notProposed = diag.not_proposed.filter(x => x.element === el)
  const r5 = diag.issues.filter(i => i.rule?.startsWith('R5') && i.severity !== 'info')
  const hasAside = r5.length > 0 || notProposed.length > 0
  const hasFlowsheet = !!fsInfo?.flowsheet

  return (
    <div className="space-y-4 animate-in">
      <PageHeader title="Карта потерь"
        subtitle="Где и в какой минеральной форме теряется металл"
        actions={<>
          {reports && reports.length > 1 && (
            <select className="select w-auto" value={tailType} onChange={e => setTailType(e.target.value)}>
              {reports.map(r => <option key={r.tail_type}>{r.tail_type}</option>)}
            </select>
          )}
          <Segmented options={ELEMENTS} value={el} onChange={setEl} />
          <button className="btn btn-primary" onClick={() => nav(`/p/${pid}/hypotheses`)}>
            К гипотезам <Icon name="arrowRight" />
          </button>
        </>} />

      {/* тепловая карта — на всю ширину, сверху */}
      <Panel
        title={<span className="flex items-center gap-2">
          <Badge tone={el === 'Ni' ? 'brand' : 'warn'}>{el}</Badge>
          Тепловая карта потерь
        </span>}
        subtitle={<>
          потери <span className="num">{fmt.t(report.losses_tonnes[el])} т</span> ·
          извлекаемо <span className="num" style={{ color: 'var(--c-ok)' }}>
            {fmt.pct(report.recoverable_pct[el])}</span>
        </>}
        bodyClass="p-3">
        <HeatTable el={el} diag={diag} />
      </Panel>

      {/* низ: слева диагнозы + «почему не предложено», справа — узкая высокая схема фабрики */}
      <div className={hasFlowsheet ? 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] items-start' : ''}>
        {/* левая колонка: диагнозы, затем «почему не предложено» */}
        <div className="space-y-4 min-w-0">
        {/* диагнозы */}
        <section className="flex flex-col gap-2 min-w-0">
          <SectionLabel>Диагнозы {el} · {diagnoses.length}</SectionLabel>
          {diagnoses.length === 0
            ? <EmptyBox text={`Для ${el} правила диагностики не сработали`} icon="target" />
            : (
              <div className={`grid gap-3 auto-rows-fr ${diagnoses.length > 1 ? 'sm:grid-cols-2' : ''}`}>
                {diagnoses.map(d => {
                  const key = d.rule_id + d.element
                  return (
                    <div key={key} data-hl={`rule:${d.rule_id}`}
                      className="card p-3 space-y-2 animate-in flex flex-col h-full">
                      <div className="flex items-center gap-2">
                        <button type="button" title="показать правило" className="shrink-0"
                          onClick={() => setOpenRule(openRule === key ? null : key)}>
                          <Badge tone="solid" className="num cursor-pointer">{d.rule_id}</Badge>
                        </button>
                        <span className="font-semibold text-sm leading-tight">{d.title}</span>
                        {d.uncertain && <Badge tone="warn">неуверенно</Badge>}
                      </div>
                      <p className="text-sm leading-relaxed flex-1">{d.text}</p>
                      {openRule === key && (
                        <pre className="text-xs num bg-surface-2 border border-line rounded-md p-2 overflow-x-auto"
                          style={{ color: 'var(--c-muted)' }}>
                          {JSON.stringify(d.inputs, null, 1)}
                        </pre>
                      )}
                      <button className="btn btn-primary w-full justify-center mt-auto"
                        onClick={() => nav(`/p/${pid}/hypotheses`)}>
                        <Icon name="spark" />
                        Сгенерировать гипотезы (извлекаемо <span className="num">{fmt.t(d.tonnes_recoverable, 0)}</span> т)
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
        </section>

        {/* аномалии данных + «почему не предложено» */}
        {hasAside && (
          <section className="flex flex-col gap-2 min-w-0">
            <SectionLabel>Почему не предложено {el}</SectionLabel>
            <div className="flex flex-col gap-3">
              {notProposed.length > 0 && (
                <div className="card p-3">
                  <ul className="space-y-1.5">
                    {notProposed.map((x, n) => (
                      <li key={n} className="text-xs" style={{ color: 'var(--c-muted)' }}>
                        <span className="font-medium text-faint">🔒 {x.form}</span>
                        <span className="num"> · {fmt.t(x.tonnes, 0)} т</span> — {x.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {r5.length > 0 && (
                <div className="card p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-sm text-warn mb-2">
                    <Icon name="alert" className="w-4 h-4" />
                    Аномалии данных (R5)
                  </div>
                  <ul className="space-y-1.5">
                    {r5.slice(0, 8).map((i, n) => (
                      <li key={n} className="text-xs bg-warn-tint text-warn rounded-md p-2">
                        {i.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>
        )}
        </div>{/* /левая колонка */}

        {/* правая колонка: схема фабрики — узкая, занимает высоту */}
        {fsInfo?.flowsheet && (
          <div className="min-w-0">
            <FlowsheetGraph factory={fsInfo.factory} fs={fsInfo.flowsheet}
              highlight={new Set(diag.diagnoses.flatMap(d => d.node_refs ?? []))} />
          </div>
        )}
      </div>
    </div>
  )
}
