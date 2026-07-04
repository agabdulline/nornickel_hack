import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { LossCell, TailingsReport } from '../types'
import {
  Badge, ErrorBox, Icon, PageHeader, Panel, SectionLabel, Segmented, Spinner, StatCard,
} from '../components/common'

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
      <div className="max-w-xl mx-auto mt-12 space-y-4 animate-in">
        {err && <ErrorBox error={err} />}
        <div className="card p-10 text-center border-2 border-dashed border-line-strong">
          <div className="grid place-items-center w-14 h-14 mx-auto rounded-2xl mb-4"
            style={{ background: 'var(--c-brand-tint)', color: 'var(--c-brand)' }}>
            <Icon name="doc" className="w-7 h-7" />
          </div>
          <div className="font-bold text-base mb-1">
            Загрузите отчёт института по хвостам (.xlsx)
          </div>
          <div className="text-sm text-muted mb-5">
            Битые значения (<span className="num">#REF!</span>) не страшны — система
            восстановит их и подсветит.
          </div>
          <input ref={fileRef} type="file" accept=".xlsx" className="hidden"
            onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
          <button className="btn btn-primary btn-lg" disabled={uploading}
            onClick={() => fileRef.current?.click()}>
            <Icon name="upload" />
            {uploading ? 'Разбираю…' : 'Выбрать файл'}
          </button>
        </div>
      </div>
    )
  }

  const issues = report.issues.filter(i => i.severity !== 'info')

  return (
    <div className="space-y-4 animate-in">
      <PageHeader title="Разбор отчёта"
        actions={<>
          {reports.length > 1 && (
            <Segmented options={reports.map(r => r.tail_type)} value={tailType} onChange={setTailType} />
          )}
          <button className="btn" disabled={uploading} onClick={() => fileRef.current?.click()}>
            <Icon name="refresh" />
            {uploading ? 'Разбираю…' : 'Заменить файл'}
          </button>
          <button className="btn btn-primary" onClick={() => nav(`/p/${pid}/map`)}>
            Подтвердить <Icon name="arrowRight" /> Диагностика
          </button>
        </>} />
      <input ref={fileRef} type="file" accept=".xlsx" className="hidden"
        onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />

      {err && <ErrorBox error={err} />}

      {/* сводка KPI */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger">
        <StatCard label="Отвальные хвосты, СМТ" value={fmt.t(report.tails_tonnes, 0)} icon="factory" />
        <StatCard label="Потери Ni" tone="loss" icon="chart"
          value={`${fmt.t(report.losses_tonnes.Ni)} т`} sub={fmt.pct(report.grade.Ni, 4)} />
        <StatCard label="Потери Cu" tone="loss" icon="chart"
          value={`${fmt.t(report.losses_tonnes.Cu)} т`} sub={fmt.pct(report.grade.Cu, 4)} />
        <StatCard label="Извлекаемо Ni / Cu" tone="ok" icon="target"
          value={`${fmt.pct(report.recoverable_pct.Ni)} / ${fmt.pct(report.recoverable_pct.Cu)}`}
          sub={`${fmt.t(report.recoverable_total.Ni, 0)} т / ${fmt.t(report.recoverable_total.Cu, 0)} т`} />
      </div>

      {/* баннер восстановленных значений */}
      {recovered.length > 0 && (
        <div className="card p-3.5 flex items-center gap-3 flex-wrap bg-warn-tint"
          style={{ borderColor: 'color-mix(in srgb, var(--c-warn) 35%, var(--c-line))' }}>
          <span className="grid place-items-center w-8 h-8 rounded-full shrink-0 text-warn"
            style={{ background: 'color-mix(in srgb, var(--c-warn) 16%, transparent)' }}>
            <Icon name="alert" className="w-4 h-4" />
          </span>
          <span className="text-sm text-warn">
            Восстановлено <span className="num font-semibold">{recovered.length}</span> значений —
            проверьте (пунктирные ячейки, тултип с формулой)
          </span>
          <button className="btn btn-ok btn-sm ml-auto" onClick={acceptAllRecovered}>
            <Icon name="check" />
            Принять все восстановленные
          </button>
        </div>
      )}

      {/* замечания к данным */}
      {issues.length > 0 && (
        <details className="card p-4">
          <summary className="flex items-center gap-2 text-sm font-semibold text-warn cursor-pointer select-none">
            <Icon name="alert" className="w-4 h-4" />
            Замечания к данным: <span className="num">{issues.length}</span>
          </summary>
          <ul className="mt-3 space-y-1.5 stagger">
            {issues.map((i, n) => (
              <li key={n}
                className={'flex items-start gap-2 text-xs rounded-md p-2 border border-line ' +
                  (i.severity === 'error' ? 'bg-danger-tint text-danger' : 'bg-warn-tint text-warn')}>
                {i.rule && <span className="num font-semibold shrink-0 opacity-80">[{i.rule}]</span>}
                <span>{i.message}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* таблица крупности */}
      <Panel title="Классы крупности" bodyClass="p-2 sm:p-3">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Класс, мкм</th>
                <th className="text-right">Доля класса</th>
                <th className="text-right">Доля Ni</th>
                <th className="text-right">Ni, т</th>
                <th className="text-right">Доля Cu</th>
                <th className="text-right">Cu, т</th>
              </tr>
            </thead>
            <tbody>
              {report.size_classes.map(s => (
                <tr key={s.label}>
                  <td className="num font-semibold">{s.label}</td>
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
      </Panel>

      {/* минералогия по классам */}
      <Panel title="Минералогия, т" subtitle="Клик по ячейке для правки" bodyClass="p-2 sm:p-3">
        <div className="overflow-x-auto">
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
                      <td className="num font-semibold whitespace-nowrap">
                        {si === 0 && (
                          <Badge tone={el === 'Ni' ? 'brand' : 'warn'} className="mr-1.5">{el}</Badge>
                        )}
                        {s.label}
                      </td>
                      {FORMS.map(f => {
                        const c = byForm[f]
                        if (!c) return <td key={f} className="text-right text-faint">—</td>
                        const rec = c.provenance !== 'measured'
                        return (
                          <td key={f}
                            className={'num text-right cursor-pointer transition-colors hover:bg-brand-tint ' +
                              (rec ? 'recovered-cell ' : '') +
                              (!c.recoverable ? 'text-faint' : '')}
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
        <SectionLabel>
          <span className="inline-flex items-center gap-1.5 mt-2">
            <span className="recovered-cell inline-block w-3 h-3 rounded-sm" />
            восстановленные значения · 🔒 неизвлекаемые формы приглушены
          </span>
        </SectionLabel>
      </Panel>
    </div>
  )
}
