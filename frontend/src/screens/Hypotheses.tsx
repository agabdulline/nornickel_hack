import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, fmt } from '../api'
import type { Hypothesis } from '../types'
import { CapexBadge, ChunkModal, EmptyBox, ErrorBox, Spinner } from '../components/common'

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
    <div className="flex gap-4 items-start">
      {/* левая панель */}
      <aside className="w-64 shrink-0 space-y-4 sticky top-16">
        <div className="card p-3 space-y-3">
          <div className="font-semibold text-sm">Веса ранжирования</div>
          {Object.entries(weights).map(([k, v]) => (
            <label key={k} className="block text-xs text-slate-600">
              {W_LABELS[k]} <span className="num float-right">{v.toFixed(2)}</span>
              <input type="range" min={0} max={1} step={0.05} value={v}
                className="w-full"
                onChange={e => setWeights(w => ({ ...w, [k]: Number(e.target.value) }))} />
            </label>
          ))}
        </div>
        <div className="card p-3 space-y-2">
          <div className="font-semibold text-sm">Переделы</div>
          {AREAS.map(a => (
            <label key={a} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={areaFilter.includes(a)}
                onChange={e => setAreaFilter(f =>
                  e.target.checked ? [...f, a] : f.filter(x => x !== a))} />
              {a}
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm pt-2 border-t border-slate-100">
            <input type="checkbox" checked={noCapex} onChange={e => setNoCapex(e.target.checked)} />
            без капзатрат
          </label>
        </div>
        <div className="card p-3 space-y-2">
          <div className="font-semibold text-sm">Исключения / ограничения</div>
          <textarea className="w-full border border-slate-300 rounded px-2 py-1 text-sm" rows={3}
            placeholder="напр.: не трогать реагентный режим"
            value={exclusions} onChange={e => setExclusions(e.target.value)} />
        </div>
        <button className="btn btn-primary w-full justify-center" disabled={busy} onClick={generate}>
          {busy ? 'Генерация… (до 5 мин)' : '⚡ Сгенерировать гипотезы'}
        </button>
      </aside>

      {/* карточки */}
      <div className="flex-1 space-y-3 min-w-0">
        {err && <ErrorBox error={err} />}
        {hyps !== null && hyps.length > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={showMissingEquipment}
                onChange={e => setShowMissingEquipment(e.target.checked)} />
              Показывать гипотезы, требующие нового оборудования
            </label>
            {!showMissingEquipment && hiddenForEquipment > 0 && (
              <span className="text-slate-400">
                (скрыто {hiddenForEquipment} — нет оборудования на линии)
              </span>
            )}
          </div>
        )}
        {hyps === null && !err && <Spinner />}
        {hyps !== null && visible.length === 0 &&
          <EmptyBox text="Гипотез пока нет" hint="Нажмите «Сгенерировать гипотезы» слева" />}
        {visible.map((h, i) => (
          <HypCard key={h.id} h={h} rank={i + 1} onFeedback={feedback}
            onChunk={(id, quote) => setChunk({ id, quote })} />
        ))}
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
  const statusStyle: Record<string, string> = {
    accepted: 'border-l-4 border-l-green-500',
    rejected: 'border-l-4 border-l-red-400 opacity-60',
  }
  const expertMatch = (h.novelty?.prior_matches?.length ?? 0) > 0
  const missing = h.equipment.filter(e => !e.present_on_plant)
  const present = h.equipment.filter(e => e.present_on_plant)

  return (
    <div className={`card ${statusStyle[h.status] ?? ''}`}>
      <div className="p-3 flex items-start gap-3 cursor-pointer" onClick={() => setOpen(o => !o)}>
        <div className="num text-2xl text-slate-300 font-bold w-8 text-right shrink-0">{rank}</div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold leading-snug">{h.title}</div>
          <div className="flex flex-wrap gap-1.5 mt-1.5 items-center">
            <span className="badge bg-teal-50 text-teal-800">{h.process_area}</span>
            <span className="badge bg-slate-100 text-slate-700">{h.element}</span>
            <CapexBadge capex={h.feasibility?.capex} />
            <span className="badge bg-slate-100 text-slate-700">риски: {h.risks.length}</span>
            {missing.length > 0 && (
              <span className="badge bg-amber-100 text-amber-800">
                ⚠ требует нового оборудования (CAPEX)
              </span>
            )}
            {missing.length === 0 && present.length > 0 && (
              <span className="badge bg-green-100 text-green-800">
                ✓ {present.map(e => e.name).join(', ')} есть
                {present.some(e => e.positions.length > 0) &&
                  `, позиции ${present.flatMap(e => e.positions).join(', ')}`}
              </span>
            )}
            {h.diagnosis_rule && <span className="badge bg-slate-100 text-slate-600">[{h.diagnosis_rule}]</span>}
            {expertMatch &&
              <span className="badge bg-green-100 text-green-800">✓ Совпадает с гипотезой экспертов</span>}
            {h.uncertain &&
              <span className="badge bg-amber-100 text-amber-800">оценка на восстановленных данных</span>}
            {h.status === 'accepted' && <span className="badge bg-green-600 text-white">принята</span>}
            {h.status === 'rejected' && <span className="badge bg-red-100 text-red-700">отклонена</span>}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="num font-semibold">до {fmt.t(h.effect.tonnes_expected, 0)} т {h.element}/год</div>
          <div className="num text-sm text-slate-500">≈ {fmt.usd(h.effect.money_usd)}</div>
          <div className="mt-1 w-28 h-1.5 bg-slate-100 rounded overflow-hidden ml-auto"
            title={`score ${h.score.toFixed(3)}`}>
            <div className="h-full bg-teal-600" style={{ width: `${Math.min(h.score * 100, 100)}%` }} />
          </div>
        </div>
      </div>

      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-100 space-y-3">
          <p className="text-sm leading-relaxed">{h.mechanism}</p>

          {h.rationale.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {h.rationale.map((c, i) => (
                <button key={i}
                  className={`badge cursor-pointer max-w-md truncate border ${c.verified
                    ? 'bg-teal-50 text-teal-900 border-teal-200 hover:bg-teal-100'
                    : 'bg-amber-50 text-amber-900 border-amber-200 hover:bg-amber-100'}`}
                  title={c.quote}
                  onClick={() => c.chunk_id && onChunk(c.chunk_id, c.quote)}>
                  {c.verified ? '📖' : '⚠'} «{c.quote.slice(0, 60)}…»
                  {c.source && ` — ${c.source.slice(0, 30)}${c.page ? `, с.${c.page}` : ''}`}
                  {!c.verified && ' · требует проверки'}
                </button>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-4 text-sm">
            <div>
              <div className="text-xs text-slate-500 mb-1">Целевые ячейки потерь</div>
              <div className="flex flex-wrap gap-1">
                {h.target_cells.map(tc => (
                  <span key={tc.key} className="badge bg-red-50 text-red-800 num">
                    {tc.key} · {fmt.t(tc.tonnes, 0)} т
                  </span>
                ))}
              </div>
            </div>
            {h.equipment.length > 0 && (
              <div>
                <div className="text-xs text-slate-500 mb-1">Оборудование</div>
                <div className="flex flex-wrap gap-1">
                  {h.equipment.map((e, i) => (
                    <span key={i} className={`badge ${e.present_on_plant
                      ? 'bg-green-50 text-green-800' : 'bg-amber-50 text-amber-800'}`}>
                      {e.present_on_plant ? '✓' : '✗'} {e.name}
                      {e.positions.length > 0 && ` (${e.positions.join(', ')})`}
                      {!e.present_on_plant && ' — нет на фабрике'}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {h.risks.length > 0 && (
            <div className="text-sm"><span className="text-xs text-slate-500">Риски: </span>
              {h.risks.join('; ')}</div>
          )}

          {h.verification_plan.length > 0 && (
            <div>
              <div className="text-xs text-slate-500 mb-1.5">План проверки</div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {h.verification_plan.map(s => (
                  <div key={s.n} className="border border-slate-200 rounded p-2 min-w-56 text-xs bg-slate-50">
                    <div className="font-semibold">{s.n}. {s.action}</div>
                    <div className="text-slate-500 mt-0.5">{s.duration}{s.resources && ` · ${s.resources}`}</div>
                    <div className="mt-1 text-green-700">✓ {s.success_criterion}</div>
                    {s.fail_criterion && <div className="text-red-700">✗ {s.fail_criterion}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="text-xs text-slate-400">{h.effect.assumptions}</div>

          <div className="flex gap-2 pt-1 border-t border-slate-100">
            <button className="btn btn-ok" onClick={e => { e.stopPropagation(); onFeedback(h, 'accept') }}>
              ✓ Принять
            </button>
            <button className="btn btn-danger" onClick={e => { e.stopPropagation(); onFeedback(h, 'reject') }}>
              ✕ Отклонить…
            </button>
            <span className="ml-auto num text-xs text-slate-400 self-center">
              score {h.score.toFixed(3)} · id {h.id}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
