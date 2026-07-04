import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { Hypothesis } from '../types'
import {
  Badge, CapexBadge, ChunkModal, EmptyBox, ErrorBox, Icon, Meter, Panel,
  SectionLabel, Spinner,
} from '../components/common'

const AREAS = ['дробление', 'измельчение', 'классификация', 'флотация', 'реагентика', 'вспомогательные']
const W_LABELS: Record<string, string> = {
  money: 'Экономика', capex: 'Дешевизна внедрения', risk: 'Низкий риск', novelty: 'Новизна',
}

export default function Hypotheses() {
  const { pid = '' } = useParams()
  const [hyps, setHyps] = useState<Hypothesis[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [weights, setWeights] = useState<Record<string, number>>(
    { money: 0.4, capex: 0.25, risk: 0.2, novelty: 0.15 })
  const [areaFilter, setAreaFilter] = useState<string[]>([])
  const [noCapex, setNoCapex] = useState(false)
  const [showMissingEquipment, setShowMissingEquipment] = useState(false)
  const [exclusions, setExclusions] = useState('')
  const [chunk, setChunk] = useState<{ id: string; quote: string } | null>(null)

  useEffect(() => {
    api.hypotheses(pid).then(setHyps).catch(e => setErr(String(e)))
  }, [pid])

  const generate = async () => {
    setBusy(true); setErr('')
    try {
      // чекбоксы переделов — клиентский фильтр отображения;
      // текстовые исключения уходят в промпт как ограничения
      const res = await api.generate(pid, { weights, constraints: exclusions || undefined })
      setHyps(res)
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const missingEquipment = (h: Hypothesis) => h.equipment.some(e => !e.present_on_plant)

  const passesBaseFilters = useMemo(() => (hyps ?? []).filter(h => {
    if (areaFilter.length && !areaFilter.includes(h.process_area)) return false
    if (noCapex && String(h.feasibility?.capex).toLowerCase() === 'high') return false
    return true
  }), [hyps, areaFilter, noCapex])
  const visible = useMemo(() =>
    passesBaseFilters.filter(h => showMissingEquipment || !missingEquipment(h)),
    [passesBaseFilters, showMissingEquipment])
  const hiddenForEquipment = passesBaseFilters.length - visible.length

  const feedback = async (h: Hypothesis, action: 'accept' | 'reject') => {
    let reason = ''
    if (action === 'reject') {
      reason = window.prompt('Причина отклонения (уйдёт в стоп-лист регенерации):') ?? ''
      if (reason === '') return
    }
    try {
      await api.feedback(h.id, action, reason)
      setHyps(hs => (hs ?? []).map(x =>
        x.id === h.id ? { ...x, status: action === 'accept' ? 'accepted' : 'rejected' } : x))
    } catch (e) { setErr(String(e)) }
  }

  return (
    <div className="space-y-4 animate-in">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-extrabold">Гипотезы</h1>
        <span className="text-sm text-muted">Ранжирование по вашим весам</span>
      </div>

      <div className="flex gap-4 items-start">
        {/* левая панель */}
        <aside className="w-64 shrink-0 space-y-4 sticky top-16">
          <Panel title="Веса ранжирования" bodyClass="p-4 space-y-3.5">
            {Object.entries(weights).map(([k, v]) => (
              <label key={k} className="block">
                <span className="field-label">{W_LABELS[k]}</span>
                <span className="num float-right text-muted">{v.toFixed(2)}</span>
                <input type="range" min={0} max={1} step={0.05} value={v}
                  className="w-full mt-1.5 block"
                  onChange={e => setWeights(w => ({ ...w, [k]: Number(e.target.value) }))} />
              </label>
            ))}
          </Panel>

          <Panel title="Переделы" bodyClass="p-4 space-y-2">
            {AREAS.map(a => (
              <label key={a} className="flex items-center gap-2 text-sm cursor-pointer text-text">
                <input type="checkbox" checked={areaFilter.includes(a)}
                  style={{ accentColor: 'var(--c-brand)' }}
                  onChange={e => setAreaFilter(f =>
                    e.target.checked ? [...f, a] : f.filter(x => x !== a))} />
                {a}
              </label>
            ))}
            <label className="flex items-center gap-2 text-sm pt-2 border-t border-line cursor-pointer text-text">
              <input type="checkbox" checked={noCapex}
                style={{ accentColor: 'var(--c-brand)' }}
                onChange={e => setNoCapex(e.target.checked)} />
              без капзатрат
            </label>
            <label className="flex items-start gap-2 text-sm cursor-pointer text-text leading-snug">
              <input type="checkbox" checked={showMissingEquipment}
                className="mt-0.5"
                style={{ accentColor: 'var(--c-brand)' }}
                onChange={e => setShowMissingEquipment(e.target.checked)} />
              показывать требующие нового оборудования
            </label>
          </Panel>

          <Panel title="Исключения / ограничения" bodyClass="p-4">
            <textarea className="textarea" rows={3}
              placeholder="напр.: не трогать реагентный режим"
              value={exclusions} onChange={e => setExclusions(e.target.value)} />
          </Panel>

          <button className="btn btn-primary w-full justify-center" disabled={busy} onClick={generate}>
            {busy ? 'Генерация… (до 5 мин)' : (<><Icon name="spark" />Сгенерировать гипотезы</>)}
          </button>
        </aside>

        {/* карточки */}
        <div className="flex-1 space-y-3 min-w-0">
          {err && <ErrorBox error={err} />}
          {hyps === null && !err && <Spinner />}
          {hyps !== null && visible.length === 0 &&
            <EmptyBox text="Гипотез пока нет" hint="Нажмите «Сгенерировать гипотезы» слева" icon="flask" />}
          <div className="space-y-3 stagger">
            {visible.map((h, i) => (
              <HypCard key={h.id} h={h} rank={i + 1} onFeedback={feedback}
                onChunk={(id, quote) => setChunk({ id, quote })} />
            ))}
          </div>
          {!showMissingEquipment && hiddenForEquipment > 0 && (
            <div className="card-2 p-3 text-xs text-muted flex items-start gap-2">
              <Icon name="alert" className="w-3.5 h-3.5 shrink-0 mt-0.5 text-warn" />
              <span>
                Скрыто <span className="num">{hiddenForEquipment}</span> —{' '}
                {hiddenForEquipment === 1 ? 'гипотеза требует' : 'гипотез требуют'} оборудования,
                которого нет на линии. Включите «показывать требующие нового оборудования»
                в фильтрах слева.
              </span>
            </div>
          )}
        </div>
      </div>

      {chunk && <ChunkModal chunkId={chunk.id} quote={chunk.quote} onClose={() => setChunk(null)} />}
    </div>
  )
}

function HypCard({ h, rank, onFeedback, onChunk }: {
  h: Hypothesis; rank: number
  onFeedback: (h: Hypothesis, a: 'accept' | 'reject') => void
  onChunk: (id: string, quote: string) => void
}) {
  const [open, setOpen] = useState(rank === 1)
  const expertMatch = (h.novelty?.prior_matches?.length ?? 0) > 0
  const missing = h.equipment.filter(e => !e.present_on_plant)
  const present = h.equipment.filter(e => e.present_on_plant)

  const accent = h.status === 'accepted'
    ? { borderLeft: '4px solid var(--c-ok)' }
    : h.status === 'rejected'
      ? { borderLeft: '4px solid var(--c-danger)' }
      : undefined

  return (
    <div className={`card hover-lift ${h.status === 'rejected' ? 'opacity-60' : ''}`} style={accent}>
      <div className="p-3 flex items-start gap-3 cursor-pointer" onClick={() => setOpen(o => !o)}>
        <div className="num text-2xl font-bold w-8 text-right shrink-0 text-faint">{rank}</div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold leading-snug">{h.title}</div>
          <div className="flex flex-wrap gap-1.5 mt-1.5 items-center">
            <Badge tone="brand">{h.process_area}</Badge>
            <Badge>{h.element}</Badge>
            <CapexBadge capex={h.feasibility?.capex} />
            <Badge>риски: <span className="num">{h.risks.length}</span></Badge>
            {missing.length > 0 && (
              <Badge tone="warn">
                <Icon name="alert" className="w-3 h-3 shrink-0" />требует нового оборудования (CAPEX)
              </Badge>
            )}
            {missing.length === 0 && present.length > 0 && (
              <Badge tone="ok">
                <Icon name="check" className="w-3 h-3 shrink-0" />
                {present.map(e => e.name).join(', ')} есть
                {present.some(e => e.positions.length > 0) &&
                  `, позиции ${present.flatMap(e => e.positions).join(', ')}`}
              </Badge>
            )}
            {h.diagnosis_rule && <Badge><span className="num">[{h.diagnosis_rule}]</span></Badge>}
            {expertMatch && (
              <Badge tone="ok"><Icon name="check" className="w-3 h-3" />Совпадает с гипотезой экспертов</Badge>
            )}
            {h.uncertain && <Badge tone="warn">оценка на восстановленных данных</Badge>}
            {h.status === 'accepted' && <Badge tone="solid">принята</Badge>}
            {h.status === 'rejected' && <Badge tone="danger">отклонена</Badge>}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="num font-semibold">до {fmt.t(h.effect.tonnes_expected, 0)} т {h.element}/год</div>
          <div className="num text-sm text-muted">≈ {fmt.usd(h.effect.money_usd)}</div>
          <Meter value={h.score} title={`score ${h.score.toFixed(3)}`} className="w-28 ml-auto mt-1.5" />
        </div>
      </div>

      {open && (
        <div className="px-3 pb-3 pt-3 border-t border-line space-y-3">
          <p className="text-sm leading-relaxed">{h.mechanism}</p>

          {h.rationale.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {h.rationale.map((c, i) => (
                <button key={i}
                  className={`badge ${c.verified ? 'badge-brand' : 'badge-warn'} max-w-md cursor-pointer`}
                  title={c.quote}
                  onClick={() => c.chunk_id && onChunk(c.chunk_id, c.quote)}>
                  <Icon name={c.verified ? 'book' : 'alert'} className="w-3 h-3 shrink-0" />
                  <span className="truncate min-w-0">
                    «{c.quote.slice(0, 60)}…»
                    {c.source && ` — ${c.source.slice(0, 30)}${c.page ? `, с.${c.page}` : ''}`}
                    {!c.verified && ' · требует проверки'}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm">
            <div>
              <SectionLabel>Целевые ячейки потерь</SectionLabel>
              <div className="flex flex-wrap gap-1">
                {h.target_cells.map(tc => (
                  <Badge key={tc.key} tone="danger" className="num">
                    {tc.key} · {fmt.t(tc.tonnes, 0)} т
                  </Badge>
                ))}
              </div>
            </div>
            {h.equipment.length > 0 && (
              <div>
                <SectionLabel>Оборудование</SectionLabel>
                <div className="flex flex-wrap gap-1">
                  {h.equipment.map((e, i) => (
                    <Badge key={i} tone={e.present_on_plant ? 'ok' : 'warn'}>
                      <Icon name={e.present_on_plant ? 'check' : 'x'} className="w-3 h-3 shrink-0" />
                      {e.name}
                      {e.positions.length > 0 && ` (${e.positions.join(', ')})`}
                      {!e.present_on_plant && ' — нет на фабрике'}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>

          {h.risks.length > 0 && (
            <div className="text-sm">
              <span className="text-xs text-muted">Риски: </span>
              {h.risks.join('; ')}
            </div>
          )}

          {h.verification_plan.length > 0 && (
            <div>
              <SectionLabel>План проверки</SectionLabel>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {h.verification_plan.map(s => (
                  <div key={s.n} className="card-2 p-2 min-w-56 text-xs">
                    <div className="font-semibold"><span className="num">{s.n}.</span> {s.action}</div>
                    <div className="text-muted mt-0.5">{s.duration}{s.resources && ` · ${s.resources}`}</div>
                    <div className="mt-1 flex items-start gap-1 text-ok">
                      <Icon name="check" className="w-3 h-3 mt-0.5 shrink-0" />{s.success_criterion}
                    </div>
                    {s.fail_criterion && (
                      <div className="flex items-start gap-1 text-danger">
                        <Icon name="x" className="w-3 h-3 mt-0.5 shrink-0" />{s.fail_criterion}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="text-xs text-faint">{h.effect.assumptions}</div>

          <div className="flex gap-2 pt-3 border-t border-line items-center">
            <button className="btn btn-ok" onClick={e => { e.stopPropagation(); onFeedback(h, 'accept') }}>
              <Icon name="check" />Принять
            </button>
            <button className="btn btn-danger" onClick={e => { e.stopPropagation(); onFeedback(h, 'reject') }}>
              <Icon name="x" />Отклонить…
            </button>
            <span className="ml-auto num text-xs text-faint self-center">
              score {h.score.toFixed(3)} · id {h.id}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
