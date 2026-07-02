import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { Hypothesis, RoadmapItem } from '../types'
import { ErrorBox, Spinner } from '../components/common'

export default function ExportScreen() {
  const { pid = '' } = useParams()
  const [tab, setTab] = useState<'report' | 'roadmap'>('report')
  const [hyps, setHyps] = useState<Hypothesis[] | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => { api.hypotheses(pid).then(setHyps).catch(e => setErr(String(e))) }, [pid])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold mr-2">Отчёт и экспорт</h1>
        {(['report', 'roadmap'] as const).map(t => (
          <button key={t}
            className={`px-3 py-1 rounded text-sm ${tab === t
              ? 'bg-teal-700 text-white' : 'bg-white border border-slate-300 hover:bg-slate-50'}`}
            onClick={() => setTab(t)}>
            {t === 'report' ? 'Отчёт' : 'Дорожная карта'}
          </button>
        ))}
        <div className="ml-auto flex gap-2">
          <a className="btn" href={`/api/projects/${pid}/export/docx`}>⬇ DOCX</a>
          <a className="btn" href={`/api/projects/${pid}/export/tasks.csv`}>⬇ tasks.csv</a>
          <a className="btn" href={`/api/projects/${pid}/export/json`} target="_blank">⬇ JSON</a>
        </div>
      </div>
      {err && <ErrorBox error={err} />}
      {hyps === null ? <Spinner /> :
        tab === 'report' ? <ReportTab hyps={hyps} /> : <RoadmapTab pid={pid} hyps={hyps} />}
    </div>
  )
}

function ReportTab({ hyps }: { hyps: Hypothesis[] }) {
  const cols: [string, string][] = [
    ['proposed', 'Предложены'], ['accepted', 'Приняты'],
    ['testing', 'На проверке'], ['confirmed', 'Подтверждены'], ['rejected', 'Отклонены'],
  ]
  const top = hyps.slice(0, 5)
  return (
    <div className="space-y-4">
      <div className="card p-3">
        <div className="font-semibold text-sm mb-2">Топ-5 гипотез (попадут на титул DOCX)</div>
        <table className="tbl">
          <thead><tr><th>№</th><th>Гипотеза</th><th>Передел</th>
            <th className="text-right">т/год</th><th className="text-right">$/год</th>
            <th className="text-right">score</th></tr></thead>
          <tbody>
            {top.map((h, i) => (
              <tr key={h.id}>
                <td className="num">{i + 1}</td>
                <td>{h.title}</td>
                <td>{h.process_area}</td>
                <td className="num text-right">{fmt.t(h.effect.tonnes_expected, 0)}</td>
                <td className="num text-right">{fmt.usd(h.effect.money_usd)}</td>
                <td className="num text-right">{h.score.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-5 gap-3">
        {cols.map(([status, label]) => {
          const items = hyps.filter(h => h.status === status)
          return (
            <div key={status} className="card p-2">
              <div className="text-xs font-semibold text-slate-500 mb-2 flex justify-between">
                {label} <span className="num">{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.map(h => (
                  <div key={h.id} className={`border rounded p-2 text-xs leading-snug ${
                    status === 'rejected' ? 'opacity-50 border-slate-200' :
                    status === 'accepted' ? 'border-green-300 bg-green-50' : 'border-slate-200'}`}>
                    <div className="font-medium">{h.title}</div>
                    <div className="num text-slate-500 mt-1">
                      {fmt.t(h.effect.tonnes_expected, 0)} т · {fmt.usd(h.effect.money_usd)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const STAGE_COLOR: Record<string, string> = {
  lab: 'bg-teal-200', pilot: 'bg-teal-500', rollout: 'bg-teal-800',
}
const STAGE_LABEL: Record<string, string> = {
  lab: 'лаборатория', pilot: 'ОПИ', rollout: 'тираж',
}

function RoadmapTab({ pid, hyps }: { pid: string; hyps: Hypothesis[] }) {
  const [items, setItems] = useState<RoadmapItem[] | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => { api.roadmap(pid).then(setItems).catch(() => setItems([])) }, [pid])

  const build = async () => {
    setErr('')
    try { setItems(await api.roadmapBuild(pid)) }
    catch (e) { setErr(String(e)) }
  }

  const move = async (it: RoadmapItem, weeks: number) => {
    const d = new Date(it.start)
    d.setDate(d.getDate() + weeks * 7)
    setErr('')
    try {
      const res = await api.roadmapMove(it.id, d.toISOString().slice(0, 10))
      setItems(res.items)
    } catch (e) { setErr(String(e)) }
  }

  const { t0, weeks } = useMemo(() => {
    if (!items?.length) return { t0: new Date(), weeks: 1 }
    const starts = items.map(i => +new Date(i.start))
    const ends = items.map(i => +new Date(i.end))
    const t0 = new Date(Math.min(...starts))
    const weeks = Math.max(1, Math.ceil((Math.max(...ends) - +t0) / (7 * 864e5)))
    return { t0, weeks }
  }, [items])

  if (items === null) return <Spinner />

  const accepted = hyps.filter(h => h.status === 'accepted' || h.status === 'testing')
  const byHyp = new Map<string, RoadmapItem[]>()
  items.forEach(i => byHyp.set(i.hypothesis_id, [...(byHyp.get(i.hypothesis_id) ?? []), i]))
  const wk = (d: string) => (+new Date(d) - +t0) / (7 * 864e5)
  const todayWk = (+new Date() - +t0) / (7 * 864e5)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <button className="btn btn-primary" onClick={build}>
          {items.length ? '↺ Перестроить дорожную карту' : 'Построить дорожную карту'}
        </button>
        <span className="text-sm text-slate-500">
          принятых гипотез: {accepted.length} · конфликты ресурсов разводятся автоматически
        </span>
      </div>
      {err && <ErrorBox error={err.replace('Error: ', '')} />}
      {items.length === 0 &&
        <div className="card p-8 text-center text-slate-500">
          Примите гипотезы на шаге 3 и постройте карту — стадии лаборатория → ОПИ → тираж
          с воротами и учётом занятости оборудования.
        </div>}

      {items.length > 0 && (
        <div className="card p-3 overflow-x-auto">
          {/* шкала */}
          <div className="ml-64 relative h-6 border-b border-slate-200 mb-1"
            style={{ minWidth: weeks * 28 }}>
            {Array.from({ length: Math.ceil(weeks / 4) + 1 }, (_, i) => (
              <div key={i} className="absolute text-xs text-slate-400 num"
                style={{ left: i * 4 * 28 }}>
                {new Date(+t0 + i * 4 * 7 * 864e5).toLocaleDateString('ru-RU',
                  { month: 'short', day: 'numeric' })}
              </div>
            ))}
            {todayWk >= 0 && todayWk <= weeks && (
              <div className="absolute top-0 bottom-0 w-0.5 bg-red-500" title="сегодня"
                style={{ left: todayWk * 28 }} />
            )}
          </div>

          {[...byHyp.entries()].map(([hid, stages]) => {
            const h = hyps.find(x => x.id === hid)
            return (
              <div key={hid}>
                <div className="flex items-center h-9">
                  <button className="w-64 shrink-0 text-left text-sm truncate pr-2 hover:text-teal-700"
                    title={stages[0].hypothesis_title}
                    onClick={() => setOpen(open === hid ? null : hid)}>
                    {stages[0].hypothesis_title}
                  </button>
                  <div className="relative h-6 flex-1" style={{ minWidth: weeks * 28 }}>
                    {todayWk >= 0 && todayWk <= weeks && (
                      <div className="absolute top-0 bottom-0 w-0.5 bg-red-300"
                        style={{ left: todayWk * 28 }} />
                    )}
                    {stages.map(it => (
                      <div key={it.id}
                        className={`absolute h-5 rounded-sm ${STAGE_COLOR[it.stage]}
                          flex items-center text-[10px] text-white px-1 overflow-hidden group`}
                        style={{ left: wk(it.start) * 28, width: Math.max((wk(it.end) - wk(it.start)) * 28, 12) }}
                        title={`${STAGE_LABEL[it.stage]}: ${it.start} → ${it.end}` +
                          (it.resource ? ` · ${it.resource}` : '') +
                          (it.shifted_reason ? ` · ${it.shifted_reason}` : '') +
                          `\nворота: ${it.gate_criterion}`}>
                        <span className="truncate">{STAGE_LABEL[it.stage]}</span>
                        <button
                          className="hidden group-hover:block absolute right-0.5 bg-white/80 text-slate-700 rounded px-0.5"
                          onClick={() => move(it, 1)} title="сдвинуть на неделю вправо">→</button>
                      </div>
                    ))}
                    {stages.map(it => (
                      <div key={it.id + 'g'}
                        className="absolute w-2 h-2 rotate-45 bg-slate-700 top-1.5 -ml-1"
                        style={{ left: wk(it.end) * 28 }}
                        title={`ворота: ${it.gate_criterion ?? ''}`} />
                    ))}
                    {stages.filter(s => s.shifted_reason).map(it => (
                      <div key={it.id + 's'}
                        className="absolute h-5 border-l-2 border-dashed border-slate-400 text-[10px] text-slate-400 pl-1"
                        style={{ left: wk(it.start) * 28 - 2, top: 0 }}
                        title={it.shifted_reason ?? ''}>⏳</div>
                    ))}
                  </div>
                </div>
                {open === hid && h && (
                  <div className="ml-64 mb-2 text-xs bg-slate-50 border border-slate-200 rounded p-2 space-y-1">
                    {h.verification_plan.map(s => (
                      <div key={s.n}>
                        <b>{s.n}. {s.action}</b> ({s.duration}) · успех: {s.success_criterion}
                        {s.fail_criterion && ` · провал: ${s.fail_criterion}`}
                      </div>
                    ))}
                    {stages.map(it => it.shifted_reason && (
                      <div key={it.id} className="text-slate-500">
                        ⏳ {STAGE_LABEL[it.stage]}: {it.shifted_reason}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          <div className="text-xs text-slate-400 mt-2 ml-64">
            ◆ ворота с критерием · «→» на сегменте — ручной сдвиг (при конфликте вернётся 409) ·
            красная линия — сегодня
          </div>
        </div>
      )}
    </div>
  )
}
