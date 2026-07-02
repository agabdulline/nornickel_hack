import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { LossCell, TailingsReport } from '../types'
import { ErrorBox, Spinner } from '../components/common'

const FORMS = ['Раскрытый Pnt/Cp', 'Закрытый Pnt/Cp', 'Примесь в пирротине',
  'Силикатная форма', 'Пирит', 'Миллерит']

export default function Report() {
  const { pid = '' } = useParams()
  const nav = useNavigate()
  const [reports, setReports] = useState<TailingsReport[] | null>(null)
  const [tailType, setTailType] = useState('')
  const [err, setErr] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => api.report(pid)
    .then(r => { setReports(r.reports); setTailType(t => t || r.reports[0]?.tail_type || '') })
    .catch(() => setReports([]))
  useEffect(() => { load() }, [pid])  // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (file: File) => {
    setUploading(true); setErr('')
    try {
      const res = await api.uploadReport(pid, file)
      setReports(res.reports)
      setTailType(res.reports[0]?.tail_type ?? '')
    } catch (e) { setErr(String(e)) } finally { setUploading(false) }
  }

  const report = useMemo(() =>
    reports?.find(r => r.tail_type === tailType) ?? reports?.[0], [reports, tailType])

  const recovered = useMemo(() =>
    (report?.cells ?? []).filter(c => c.provenance === 'recovered_math' || c.provenance === 'recovered_llm'),
    [report])

  const acceptAllRecovered = async () => {
    if (!report || recovered.length === 0) return
    const edits = recovered
      .filter(c => c.tonnes != null)
      .map(c => ({
        key: `${c.axes.size_class}/${c.axes.mineral_form}/${c.element}`,
        tonnes: c.tonnes!, share_pct: c.share_pct ?? undefined,
      }))
    try {
      await api.patchCells(pid, edits, report.tail_type)
      load()
    } catch (e) { setErr(String(e)) }
  }

  const editCell = async (c: LossCell) => {
    const key = `${c.axes.size_class}/${c.axes.mineral_form}/${c.element}`
    const raw = window.prompt(`Тонны для ${key}:`, String(c.tonnes ?? ''))
    if (raw == null) return
    const v = Number(raw.replace(',', '.'))
    if (!isFinite(v)) { setErr('не число'); return }
    try {
      await api.patchCells(pid, [{ key, tonnes: v }], report?.tail_type)
      load()
    } catch (e) { setErr(String(e)) }
  }

  if (reports === null) return <Spinner />

  if (!report) {
    return (
      <div className="max-w-xl mx-auto mt-12 space-y-4">
        {err && <ErrorBox error={err} />}
        <div className="card p-10 text-center border-2 border-dashed border-slate-300">
          <div className="text-4xl mb-2">📄</div>
          <div className="font-semibold mb-1">Загрузите отчёт института по хвостам (.xlsx)</div>
          <div className="text-sm text-slate-500 mb-4">
            Битые значения (#REF!) не страшны — система восстановит их и подсветит.
          </div>
          <input ref={fileRef} type="file" accept=".xlsx" className="hidden"
            onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
          <button className="btn btn-primary" disabled={uploading}
            onClick={() => fileRef.current?.click()}>
            {uploading ? 'Разбираю…' : 'Выбрать файл'}
          </button>
        </div>
      </div>
    )
  }

  const issues = report.issues.filter(i => i.severity !== 'info')

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-lg font-semibold">Разбор отчёта</h1>
        {reports.length > 1 && (
          <select className="border border-slate-300 rounded px-2 py-1 text-sm bg-white"
            value={tailType} onChange={e => setTailType(e.target.value)}>
            {reports.map(r => <option key={r.tail_type}>{r.tail_type}</option>)}
          </select>
        )}
        <button className="btn ml-auto" onClick={() => fileRef.current?.click()}>
          ↺ Заменить файл
        </button>
        <input ref={fileRef} type="file" accept=".xlsx" className="hidden"
          onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
        <button className="btn btn-primary" onClick={() => nav(`/p/${pid}/map`)}>
          Подтвердить → Диагностика
        </button>
      </div>

      {err && <ErrorBox error={err} />}

      {/* сводка карточками */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Отвальные хвосты, СМТ" value={fmt.t(report.tails_tonnes, 0)} />
        <Kpi label="Потери Ni" value={`${fmt.t(report.losses_tonnes.Ni)} т`}
          sub={fmt.pct(report.grade.Ni, 4)} tone="loss" />
        <Kpi label="Потери Cu" value={`${fmt.t(report.losses_tonnes.Cu)} т`}
          sub={fmt.pct(report.grade.Cu, 4)} tone="loss" />
        <Kpi label="Извлекаемо Ni / Cu"
          value={`${fmt.pct(report.recoverable_pct.Ni)} / ${fmt.pct(report.recoverable_pct.Cu)}`}
          sub={`${fmt.t(report.recoverable_total.Ni, 0)} т / ${fmt.t(report.recoverable_total.Cu, 0)} т`}
          tone="ok" />
      </div>

      {recovered.length > 0 && (
        <div className="card p-3 bg-amber-50 border-amber-300 flex items-center gap-3">
          <span className="text-amber-800 text-sm font-medium">
            ⚠ Восстановлено {recovered.length} значений — проверьте (пунктирные ячейки, тултип с формулой)
          </span>
          <button className="btn ml-auto" onClick={acceptAllRecovered}>
            Принять все восстановленные
          </button>
        </div>
      )}

      {issues.length > 0 && (
        <details className="card p-3">
          <summary className="text-sm font-medium text-amber-700 cursor-pointer">
            Замечания к данным: {issues.length}
          </summary>
          <ul className="mt-2 space-y-1">
            {issues.map((i, n) => (
              <li key={n} className={`text-xs rounded p-1.5 border ${i.severity === 'error'
                ? 'bg-red-50 border-red-200 text-red-800'
                : 'bg-amber-50 border-amber-200 text-amber-800'}`}>
                [{i.rule}] {i.message}
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* таблица крупности */}
      <div className="card p-3">
        <div className="font-semibold text-sm mb-2">Классы крупности</div>
        <table className="tbl">
          <thead>
            <tr><th>Класс, мкм</th><th className="text-right">Доля класса</th>
              <th className="text-right">Доля Ni</th><th className="text-right">Ni, т</th>
              <th className="text-right">Доля Cu</th><th className="text-right">Cu, т</th></tr>
          </thead>
          <tbody>
            {report.size_classes.map(s => (
              <tr key={s.label}>
                <td className="font-semibold num">{s.label}</td>
                <td className="num text-right">{fmt.pct(s.share_pct, 2)}</td>
                <td className="num text-right">{fmt.pct(s.element_share_pct.Ni, 2)}</td>
                <td className="num text-right">{fmt.t(s.element_tonnes.Ni)}</td>
                <td className="num text-right">{fmt.pct(s.element_share_pct.Cu, 2)}</td>
                <td className="num text-right">{fmt.t(s.element_tonnes.Cu)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* минералогия по классам */}
      <div className="card p-3 overflow-x-auto">
        <div className="font-semibold text-sm mb-2">
          Минералогия (т) — клик по ячейке для правки
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Класс \ Форма</th>
              {FORMS.map(f => <th key={f} className="text-right">{f}</th>)}
            </tr>
          </thead>
          <tbody>
            {['Ni', 'Cu'].map(el => (
              report.size_classes.map((s, si) => {
                const cells = report.cells.filter(c =>
                  c.element === el && c.axes.size_class === s.label)
                const byForm = Object.fromEntries(cells.map(c => [c.axes.mineral_form, c]))
                return (
                  <tr key={el + s.label}>
                    <td className="num font-semibold">
                      {si === 0 && <span className="badge bg-slate-200 text-slate-700 mr-1">{el}</span>}
                      {s.label}
                    </td>
                    {FORMS.map(f => {
                      const c = byForm[f]
                      if (!c) return <td key={f} className="text-right text-slate-300">—</td>
                      const rec = c.provenance !== 'measured'
                      return (
                        <td key={f}
                          className={`num text-right cursor-pointer hover:bg-teal-50 ` +
                            (rec ? 'recovered-cell ' : '') +
                            (!c.recoverable ? 'text-slate-400' : '')}
                          title={(rec
                            ? `Восстановлено (${c.provenance}${c.confidence != null
                              ? `, confidence ${c.confidence}` : ''}): ${c.recovery_note ?? ''}. Проверьте вручную. `
                            : '') + `${s.label}/${f}/${el}` +
                            (c.provenance === 'manual' ? ' · правка пользователя' : '')}
                          onClick={() => editCell(c)}>
                          {fmt.t(c.tonnes)}
                        </td>
                      )
                    })}
                  </tr>
                )
              })
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Kpi({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'loss' | 'ok'
}) {
  const color = tone === 'loss' ? 'text-red-700' : tone === 'ok' ? 'text-green-700' : 'text-slate-900'
  return (
    <div className="card p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`num text-xl font-bold ${color}`}>{value}</div>
      {sub && <div className="num text-xs text-slate-400">{sub}</div>}
    </div>
  )
}
