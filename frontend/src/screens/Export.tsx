import { useEffect, useMemo, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { useParams } from 'react-router-dom'
import { api, fmt, fxLabel, fxReady } from '../api'
import { DATA_CHANGED_EVENT, useChatHighlight } from '../highlight'
import type { Hypothesis, RoadmapItem } from '../types'
import { ErrorBox, Icon, Modal, PageHeader, Panel, SectionLabel, Segmented, Spinner } from '../components/common'

export default function ExportScreen() {
  const { pid = '' } = useParams()
  const [tab, setTab] = useState<'report' | 'roadmap'>('report')
  const [hyps, setHyps] = useState<Hypothesis[] | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const load = () => api.hypotheses(pid).then(setHyps).catch(e => setErr(String(e)))
    load()
    // ассистент мог принять/отклонить гипотезу или переранжировать из чата
    window.addEventListener(DATA_CHANGED_EVENT, load)
    return () => window.removeEventListener(DATA_CHANGED_EVENT, load)
  }, [pid])

  // после загрузки курса ЦБ перерисовываем суммы в ₽
  const [, setFxTick] = useState(0)
  useEffect(() => { fxReady.then(() => setFxTick(t => t + 1)) }, [])

  return (
    <div className="space-y-4 animate-in">
      <PageHeader title="Отчёт и экспорт"
        subtitle={`Эффект в ₽ по курсу ${fxLabel()}`}
        actions={<>
          <Segmented
            options={[
              { value: 'report', label: 'Отчёт' },
              { value: 'roadmap', label: 'Дорожная карта' },
            ]}
            value={tab}
            onChange={setTab}
          />
          <a className="btn" href={`/api/projects/${pid}/export/docx`}>
            <Icon name="download" /> DOCX
          </a>
          <a className="btn" href={`/api/projects/${pid}/export/tasks.csv`}>
            <Icon name="download" /> tasks.csv
          </a>
          <a className="btn" href={`/api/projects/${pid}/export/json`} target="_blank">
            <Icon name="download" /> JSON
          </a>
        </>} />

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
      <Panel title="Топ-5 гипотез (попадут на титул DOCX)" bodyClass="p-2 sm:p-3">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>№</th><th>Гипотеза</th><th>Передел</th>
                <th className="text-right">т/год</th><th className="text-right">₽/год</th>
                <th className="text-right">$/год</th><th className="text-right">score</th>
              </tr>
            </thead>
            <tbody>
              {top.map((h, i) => (
                <tr key={h.id}>
                  <td className="num font-semibold">{i + 1}</td>
                  <td>{h.title}</td>
                  <td className="text-muted">{h.process_area}</td>
                  <td className="num text-right">{fmt.t(h.effect.tonnes_expected, 0)}</td>
                  <td className="num text-right">{fmt.rub(h.effect.money_usd)}</td>
                  <td className="num text-right text-faint">{fmt.usd(h.effect.money_usd)}</td>
                  <td className="num text-right font-semibold" style={{ color: 'var(--c-brand-strong)' }}>
                    {h.score.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid grid-cols-5 gap-3 stagger">
        {cols.map(([status, label]) => {
          const items = hyps.filter(h => h.status === status)
          return (
            <div key={status} className="card-2 p-2">
              <div className="text-xs font-semibold text-muted mb-2 flex items-center justify-between">
                <span className="truncate">{label}</span>
                <span className="num">{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.map(h => {
                  const cls = status === 'rejected'
                    ? 'card p-2 text-xs leading-snug opacity-50'
                    : status === 'accepted'
                      ? 'card p-2 text-xs leading-snug bg-ok-tint'
                      : 'card p-2 text-xs leading-snug'
                  const st: CSSProperties | undefined =
                    status === 'accepted' ? { borderColor: 'var(--c-ok)' } : undefined
                  return (
                    <div key={h.id} className={cls} style={st}>
                      <div className="font-medium">{h.title}</div>
                      <div className="num text-muted mt-1">
                        {fmt.t(h.effect.tonnes_expected, 0)} т · {fmt.rub(h.effect.money_usd)}
                        <span className="text-faint"> · {fmt.usd(h.effect.money_usd)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const STAGE_STYLE: Record<string, CSSProperties> = {
  lab: { background: 'var(--c-brand-tint)', color: 'var(--c-brand-strong)' },
  pilot: { background: 'var(--c-brand)', color: '#fff' },
  rollout: { background: 'var(--c-brand-strong)', color: '#fff' },
}
const STAGE_LABEL: Record<string, string> = {
  lab: 'лаборатория', pilot: 'ОПИ', rollout: 'тираж',
}

// геометрия Ганта (даты — day-granular, работаем в UTC-полдне, чтобы часовой пояс
// не сдвигал дни при отправке PATCH)
const PXW = 30            // px на неделю
const PAD_L_W = 2         // недели слева — чтобы линия «сегодня» не липла к краю
const PAD_R_W = 5         // недели справа — запас на будущее
const DAY = 864e5, WEEK = 7 * DAY
const parseDay = (s: string) => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d, 12) }
const toISO = (ms: number) => new Date(ms).toISOString().slice(0, 10)
const ruDate = (s: string) =>
  new Date(parseDay(s)).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

function RoadmapTab({ pid, hyps }: { pid: string; hyps: Hypothesis[] }) {
  const [items, setItems] = useState<RoadmapItem[] | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  // диалог принятия ресурсного конфликта (пункт 4)
  const [conflict, setConflict] = useState<{ itemId: string; start: string; message: string } | null>(null)
  // живой драг: какую гипотезу и на сколько недель тянем
  const [drag, setDrag] = useState<{ hid: string; fromStart: number; deltaW: number } | null>(null)
  // модалка-разбор принятого конфликта (клик по значку ⚠ на стадии)
  const [explain, setExplain] = useState<RoadmapItem | null>(null)

  useEffect(() => {
    const load = () => api.roadmap(pid).then(setItems).catch(() => setItems([]))
    load()
    window.addEventListener(DATA_CHANGED_EVENT, load)
    return () => window.removeEventListener(DATA_CHANGED_EVENT, load)
  }, [pid])

  // подсветка строки Ганта, на которую указал ассистент
  useChatHighlight(items !== null)

  const build = async () => {
    setErr('')
    try { setItems(await api.roadmapBuild(pid)) }
    catch (e) { setErr(String(e)) }
  }

  // единая точка сдвига: force=false → при ресурсном конфликте открываем диалог;
  // жёсткие отказы (порядок стадий / раньше сегодня) показываем как ошибку.
  const doMove = async (itemId: string, startISO: string, force = false) => {
    setErr('')
    try {
      const res = await api.roadmapMove(itemId, startISO, force)
      setItems(res.items); setConflict(null)
    } catch (e) {
      const kind = (e as { kind?: string }).kind
      const message = (e as Error).message.replace('Error: ', '')
      if (kind === 'resource' && !force) setConflict({ itemId, start: startISO, message })
      else setErr(message)
    }
  }

  const now = new Date()
  const today0 = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate(), 12)

  const { axisStart, trackW, months } = useMemo(() => {
    const its = items ?? []
    const starts = its.map(i => parseDay(i.start))
    const ends = its.map(i => parseDay(i.end))
    const minS = Math.min(today0, ...(starts.length ? starts : [today0]))
    const maxE = Math.max(today0 + 8 * WEEK, ...(ends.length ? ends : [today0]))
    const axisStart = minS - PAD_L_W * WEEK
    const axisEnd = maxE + PAD_R_W * WEEK
    const totalW = Math.max(1, Math.ceil((axisEnd - axisStart) / WEEK))
    const mm: { x: number; label: string }[] = []
    const first = new Date(axisStart)
    let cur = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1, 12)
    while (cur <= axisEnd) {
      const cx = ((cur - axisStart) / WEEK) * PXW
      if (cx >= 0) mm.push({ x: cx,
        label: new Date(cur).toLocaleDateString('ru-RU', { month: 'short', timeZone: 'UTC' }) })
      const d = new Date(cur)
      cur = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1, 12)
    }
    return { axisStart, trackW: totalW * PXW, months: mm }
  }, [items, today0])

  if (items === null) return <Spinner />

  const accepted = hyps.filter(h => h.status === 'accepted' || h.status === 'testing')
  const byHyp = new Map<string, RoadmapItem[]>()
  items.forEach(i => byHyp.set(i.hypothesis_id, [...(byHyp.get(i.hypothesis_id) ?? []), i]))
  const xOf = (s: string) => ((parseDay(s) - axisStart) / WEEK) * PXW
  const todayX = ((today0 - axisStart) / WEEK) * PXW

  // ±неделя стрелкой (назад — не раньше сегодня)
  const nudge = (it: RoadmapItem, dir: 1 | -1) => {
    const ms = parseDay(it.start) + dir * WEEK
    if (ms < today0) return
    doMove(it.id, toISO(ms))
  }

  // drag сегмента: тянем стадию и все последующие той же гипотезы; клип «не раньше сегодня»
  const startDrag = (e: ReactPointerEvent<HTMLDivElement>, it: RoadmapItem) => {
    e.preventDefault()
    const px0 = e.clientX
    const itStart = parseDay(it.start)
    const minDeltaW = Math.ceil((today0 - itStart) / WEEK)
    const clamp = (dw: number) => Math.max(dw, minDeltaW)
    setDrag({ hid: it.hypothesis_id, fromStart: itStart, deltaW: 0 })
    const onMove = (ev: PointerEvent) =>
      setDrag(d => d ? { ...d, deltaW: clamp(Math.round((ev.clientX - px0) / PXW)) } : d)
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      setDrag(null)
      const dw = clamp(Math.round((ev.clientX - px0) / PXW))
      if (dw !== 0) doMove(it.id, toISO(itStart + dw * WEEK))
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <button className="btn btn-primary" onClick={build}>
          <Icon name={items.length ? 'refresh' : 'plus'} />
          {items.length ? 'Перестроить дорожную карту' : 'Построить дорожную карту'}
        </button>
        <span className="text-sm text-muted">
          принятых гипотез: <span className="num">{accepted.length}</span> · конфликты ресурсов
          разводятся автоматически
        </span>
      </div>

      {err && <ErrorBox error={err.replace('Error: ', '')} />}

      {items.length === 0 &&
        <div className="card p-8 text-center text-muted">
          Примите гипотезы на шаге 3 и постройте карту — стадии лаборатория → ОПИ → тираж
          с воротами и учётом занятости оборудования.
        </div>}

      {items.length > 0 && (
        <div className="card p-3 overflow-x-auto">
          {/* ось месяцев */}
          <div className="ml-64 relative h-5 mb-1" style={{ minWidth: trackW }}>
            {months.map((m, i) => (
              <div key={i} className="absolute top-0 h-full text-[11px] num text-faint pl-1 border-l"
                style={{ left: m.x, borderColor: 'var(--c-line)' }}>{m.label}</div>
            ))}
            <div className="absolute top-0 bottom-0 w-0.5 z-10" title="сегодня"
              style={{ left: todayX, background: 'var(--c-danger)' }} />
          </div>

          {[...byHyp.entries()].map(([hid, stages]) => {
            const h = hyps.find(x => x.id === hid)
            return (
              <div key={hid} data-hl={`hypothesis:${hid}`}>
                <div className="flex items-center h-9">
                  <button className="w-64 shrink-0 text-left text-sm truncate pr-2 hover:text-brand transition-colors"
                    title={stages[0].hypothesis_title}
                    onClick={() => setOpen(open === hid ? null : hid)}>
                    {stages[0].hypothesis_title}
                  </button>
                  <div className="relative h-6 flex-1" style={{ minWidth: trackW }}>
                    {/* сетка месяцев */}
                    {months.map((m, i) => (
                      <div key={'m' + i} className="absolute top-0 bottom-0 w-px"
                        style={{ left: m.x, background: 'var(--c-line)' }} />
                    ))}
                    {/* сегодня */}
                    <div className="absolute top-0 bottom-0 w-0.5"
                      style={{ left: todayX, background: 'color-mix(in srgb, var(--c-danger) 45%, transparent)' }} />
                    {/* сегменты */}
                    {stages.map(it => {
                      const dragging = !!drag && drag.hid === hid && parseDay(it.start) >= drag.fromStart
                      const dx = dragging ? drag!.deltaW * PXW : 0
                      return (
                        <div key={it.id} onPointerDown={e => startDrag(e, it)}
                          className="absolute h-5 rounded-md flex items-center text-[10px] px-1 group cursor-grab active:cursor-grabbing select-none"
                          style={{
                            left: xOf(it.start), width: Math.max(xOf(it.end) - xOf(it.start), 14), top: 2,
                            transform: dx ? `translateX(${dx}px)` : undefined,
                            opacity: dragging ? 0.85 : 1,
                            zIndex: dragging ? 20 : undefined,
                            boxShadow: it.manual_conflict ? 'inset 0 0 0 2px var(--c-danger)' : undefined,
                            ...STAGE_STYLE[it.stage],
                          }}
                          title={`${STAGE_LABEL[it.stage]}: ${ruDate(it.start)} → ${ruDate(it.end)}`
                            + (it.resource ? ` · ${it.resource}` : '')
                            + (it.shifted_reason ? ` · ${it.shifted_reason}` : '')
                            + (it.manual_conflict && it.conflict_with?.length ? `\n⚠ принятый конфликт: ${it.conflict_with.join(', ')}` : '')
                            + `\nворота: ${it.gate_criterion ?? ''}`
                            + `\nтяните или ◀ ▶ — сдвиг на неделю`}>
                          <span className="truncate pointer-events-none flex-1">{STAGE_LABEL[it.stage]}</span>
                          <button onPointerDown={e => e.stopPropagation()} onClick={() => nudge(it, -1)}
                            className="hidden group-hover:grid place-items-center absolute left-0 top-0 h-5 w-4 rounded-l-md"
                            style={{ background: 'var(--c-surface)', color: 'var(--c-text)' }} title="на неделю назад">
                            <Icon name="arrowRight" className="w-3 h-3 rotate-180" />
                          </button>
                          <button onPointerDown={e => e.stopPropagation()} onClick={() => nudge(it, 1)}
                            className="hidden group-hover:grid place-items-center absolute right-0 top-0 h-5 w-4 rounded-r-md"
                            style={{ background: 'var(--c-surface)', color: 'var(--c-text)' }} title="на неделю вперёд">
                            <Icon name="arrowRight" className="w-3 h-3" />
                          </button>
                          {it.manual_conflict && (
                            <button onPointerDown={e => e.stopPropagation()}
                              onClick={e => { e.stopPropagation(); setExplain(it) }}
                              className="absolute -top-1.5 -right-1.5 z-30 grid place-items-center w-4 h-4 rounded-full"
                              style={{ background: 'var(--c-danger)', color: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,.4)' }}
                              title="Конфликт занятости ресурса — подробнее">
                              <Icon name="alert" className="w-2.5 h-2.5" />
                            </button>
                          )}
                        </div>
                      )
                    })}
                    {/* ворота */}
                    {stages.map(it => (
                      <div key={it.id + 'g'} className="absolute w-2 h-2 rotate-45 top-2 -ml-1 pointer-events-none"
                        style={{ left: xOf(it.end), background: 'var(--c-ink)' }}
                        title={`ворота: ${it.gate_criterion ?? ''}`} />
                    ))}
                  </div>
                </div>
                {open === hid && h && (
                  <div className="card-2 ml-64 mb-2 p-2 text-xs space-y-1">
                    {h.verification_plan.map(s => (
                      <div key={s.n}>
                        <b>{s.n}. {s.action}</b> ({s.duration}) · успех: {s.success_criterion}
                        {s.fail_criterion && ` · провал: ${s.fail_criterion}`}
                      </div>
                    ))}
                    {stages.map(it => it.shifted_reason && (
                      <div key={it.id} className="text-muted">⏳ {STAGE_LABEL[it.stage]}: {it.shifted_reason}</div>
                    ))}
                    {stages.map(it => (it.manual_conflict && it.conflict_with?.length ? (
                      <div key={it.id + 'c'} style={{ color: 'var(--c-danger)' }}>
                        ⚠ {STAGE_LABEL[it.stage]}: принятый конфликт с {it.conflict_with.join(', ')}
                      </div>
                    ) : null))}
                  </div>
                )}
              </div>
            )
          })}

          <SectionLabel>
            <span className="ml-64 inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="inline-block w-2 h-2 rotate-45" style={{ background: 'var(--c-ink)' }} /> ворота с критерием ·
              тяните сегмент или ◀ ▶ (±неделя) ·
              <span className="inline-block w-2.5 h-0.5 align-middle" style={{ background: 'var(--c-danger)' }} /> сегодня ·
              <span className="inline-grid place-items-center w-3.5 h-3.5 rounded-full align-middle"
                style={{ background: 'var(--c-danger)', color: '#fff' }}><Icon name="alert" className="w-2 h-2" /></span>
              принятый конфликт — нажмите значок для разбора
            </span>
          </SectionLabel>
        </div>
      )}

      {conflict && (
        <Modal title="Конфликт занятости ресурса" onClose={() => setConflict(null)}>
          <div className="space-y-4 text-sm">
            <p>Сдвиг вызывает конфликт — общий ресурс занят другой стадией этого проекта в то же время:</p>
            <div className="card-2 p-3" style={{ color: 'var(--c-danger)' }}>{conflict.message}</div>
            <p className="text-muted">
              Можно <b>принять конфликт</b> и всё равно сдвинуть — пересекающиеся стадии
              пометятся красной рамкой. Или отменить и оставить как есть.
            </p>
            <div className="flex gap-2 justify-end">
              <button className="btn" onClick={() => setConflict(null)}>Отменить</button>
              <button className="btn btn-danger" onClick={() => doMove(conflict.itemId, conflict.start, true)}>
                Принять конфликт и сдвинуть
              </button>
            </div>
          </div>
        </Modal>
      )}

      {explain && (() => {
        const res = explain.resource
        const cap = res === 'лаборатория' ? 2 : 1
        const clash = items.filter(o => o.id !== explain.id && o.resource === res &&
          parseDay(o.start) < parseDay(explain.end) && parseDay(explain.start) < parseDay(o.end))
        return (
          <Modal title="Конфликт занятости ресурса" onClose={() => setExplain(null)}>
            <div className="space-y-4 text-sm">
              <div>
                <div className="text-xs text-muted mb-0.5">Ресурс</div>
                <div className="font-bold" style={{ color: 'var(--c-danger)' }}>{res || '—'}</div>
                <div className="text-xs text-muted mt-0.5">
                  может вести {cap === 1 ? 'только одну программу' : `не более ${cap} программ`} одновременно —
                  иначе эффекты стадий не разделить.
                </div>
              </div>
              <div>
                <div className="text-xs text-muted mb-0.5">Эта стадия</div>
                <div><b>{explain.hypothesis_title}</b> · {STAGE_LABEL[explain.stage]}</div>
                <div className="num text-xs text-muted">{ruDate(explain.start)} → {ruDate(explain.end)}</div>
              </div>
              <div>
                <div className="text-xs text-muted mb-1">
                  Идёт на этом ресурсе одновременно с {clash.length}
                  {clash.length === 1 ? ' стадией' : ' стадиями'}:
                </div>
                <div className="space-y-1.5">
                  {clash.map(o => (
                    <div key={o.id} className="card-2 p-2" style={{ boxShadow: 'inset 0 0 0 1px var(--c-danger)' }}>
                      <div><b>{o.hypothesis_title}</b> · {STAGE_LABEL[o.stage]}</div>
                      <div className="num text-xs text-muted">{ruDate(o.start)} → {ruDate(o.end)}</div>
                    </div>
                  ))}
                </div>
              </div>
              <p className="text-xs text-muted">
                Конфликт принят вручную. Чтобы снять пометку — разведите стадии по времени
                (перетащите сегмент или стрелками ◀ ▶).
              </p>
              <div className="flex justify-end">
                <button className="btn btn-primary" onClick={() => setExplain(null)}>Понятно</button>
              </div>
            </div>
          </Modal>
        )
      })()}
    </div>
  )
}
