import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { DiagnosticsResult, TailingsReport } from '../types'
import { EmptyBox, ErrorBox, Spinner } from '../components/common'

const FORMS = ['Раскрытый Pnt/Cp', 'Закрытый Pnt/Cp', 'Примесь в пирротине',
  'Силикатная форма', 'Пирит', 'Миллерит']
const CLASSES = ['+125', '-125+71', '-71+45', '-45+20', '-20+10', '-10']

export default function LossMap() {
  const { pid = '' } = useParams()
  const nav = useNavigate()
  const [reports, setReports] = useState<TailingsReport[] | null>(null)
  const [tailType, setTailType] = useState<string>('')
  const [diag, setDiag] = useState<DiagnosticsResult | null>(null)
  const [el, setEl] = useState<'Ni' | 'Cu'>('Ni')
  const [err, setErr] = useState('')
  const [openRule, setOpenRule] = useState<string | null>(null)

  useEffect(() => {
    api.report(pid)
      .then(r => { setReports(r.reports); setTailType(r.reports[0]?.tail_type ?? '') })
      .catch(e => setErr(String(e)))
  }, [pid])

  useEffect(() => {
    if (!tailType) return
    api.diagnostics(pid, tailType).then(setDiag).catch(e => setErr(String(e)))
  }, [pid, tailType])

  const report = useMemo(() =>
    reports?.find(r => r.tail_type === tailType) ?? reports?.[0], [reports, tailType])

  if (err) return <ErrorBox error={err.includes('не загружен') ?
    'Отчёт ещё не загружен — начните с шага «1 · Данные».' : err} />
  if (!report || !diag) return <Spinner />

  const map = diag.loss_map?.[el] ?? {}
  const classes = CLASSES.filter(c => map[c])
  const maxT = Math.max(1, ...classes.flatMap(c => FORMS.map(f => map[c]?.[f]?.tonnes ?? 0)))

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-semibold">Карта потерь</h1>
        {reports && reports.length > 1 && (
          <select className="border border-slate-300 rounded px-2 py-1 text-sm bg-white"
            value={tailType} onChange={e => setTailType(e.target.value)}>
            {reports.map(r => <option key={r.tail_type}>{r.tail_type}</option>)}
          </select>
        )}
        <div className="flex rounded overflow-hidden border border-slate-300">
          {(['Ni', 'Cu'] as const).map(e => (
            <button key={e}
              className={`px-4 py-1 text-sm font-medium ${el === e
                ? 'bg-teal-700 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
              onClick={() => setEl(e)}>{e}</button>
          ))}
        </div>
        <span className="text-sm text-slate-500">
          потери {el}: <b className="num">{fmt.t(report.losses_tonnes[el])} т</b> ·
          извлекаемо <b className="num text-green-700">{fmt.pct(report.recoverable_pct[el])}</b>
        </span>
      </div>

      <div className="flex gap-4 items-start">
        {/* тепловая матрица */}
        <div className="card p-3 overflow-x-auto flex-1">
          <table className="tbl">
            <thead>
              <tr>
                <th>Класс, мкм</th>
                {FORMS.map(f => {
                  const rec = map[classes[0]]?.[f]?.recoverable
                  return (
                    <th key={f} className={rec === false ? 'text-slate-400' : ''}>
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
                      if (!cell) return <td key={f} className="text-slate-300">—</td>
                      const alpha = Math.pow((cell.tonnes ?? 0) / maxT, 0.6)
                      const bg = cell.recoverable
                        ? `rgba(220, 38, 38, ${(0.06 + alpha * 0.55).toFixed(3)})`
                        : `rgba(100, 116, 139, ${(0.04 + alpha * 0.28).toFixed(3)})`
                      return (
                        <td key={f} title={`${c} / ${f} / ${el}: ${fmt.t(cell.tonnes)} т` +
                          (cell.share_pct != null ? ` (${fmt.pct(cell.share_pct)})` : '') +
                          (cell.recoverable ? ' · извлекаемо' : ' · НЕизвлекаемо') +
                          (cell.provenance !== 'measured' ? ` · ${cell.provenance}` : '')}
                          className={`num text-right ${!cell.recoverable ? 'text-slate-500' : ''} ` +
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
          <div className="text-xs text-slate-400 mt-2">
            интенсивность = тонны потерь · 🔒 приглушённые колонки — неизвлекаемые формы ·
            янтарный пунктир — восстановленные значения
          </div>
        </div>

        {/* панель диагнозов */}
        <aside className="w-96 shrink-0 space-y-3">
          <div className="font-semibold text-sm text-slate-600">Диагнозы</div>
          {diag.diagnoses.filter(d => d.element === el).length === 0 &&
            <EmptyBox text={`Для ${el} правила не сработали`} />}
          {diag.diagnoses.filter(d => d.element === el).map(d => (
            <div key={d.rule_id + d.element} className="card p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="badge bg-teal-700 text-white cursor-pointer"
                  title="показать правило"
                  onClick={() => setOpenRule(openRule === d.rule_id ? null : d.rule_id)}>
                  {d.rule_id}
                </span>
                <span className="font-semibold text-sm leading-tight">{d.title}</span>
                {d.uncertain && <span className="badge bg-amber-100 text-amber-800">неуверенно</span>}
              </div>
              <p className="text-sm leading-relaxed">{d.text}</p>
              {openRule === d.rule_id && (
                <pre className="text-xs bg-slate-50 border border-slate-200 rounded p-2 overflow-x-auto">
                  {JSON.stringify(d.inputs, null, 1)}
                </pre>
              )}
              <button className="btn btn-primary w-full justify-center"
                onClick={() => nav(`/p/${pid}/hypotheses`)}>
                Сгенерировать гипотезы (извлекаемо {fmt.t(d.tonnes_recoverable, 0)} т)
              </button>
            </div>
          ))}

          {diag.issues.filter(i => i.rule?.startsWith('R5')).length > 0 && (
            <div className="card p-3">
              <div className="font-semibold text-sm text-amber-700 mb-2">⚠ Аномалии данных (R5)</div>
              <ul className="space-y-1.5">
                {diag.issues.filter(i => i.rule?.startsWith('R5') && i.severity !== 'info')
                  .slice(0, 8).map((i, n) => (
                    <li key={n} className="text-xs bg-amber-50 border border-amber-200 rounded p-1.5">
                      {i.message}
                    </li>
                  ))}
              </ul>
            </div>
          )}

          <div className="card p-3">
            <div className="font-semibold text-sm mb-2">Почему не предложено</div>
            <ul className="space-y-1.5">
              {diag.not_proposed.filter(x => x.element === el).map((x, n) => (
                <li key={n} className="text-xs text-slate-600">
                  <span className="font-medium">🔒 {x.form}</span>
                  <span className="num"> · {fmt.t(x.tonnes, 0)} т</span> — {x.reason}
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  )
}
