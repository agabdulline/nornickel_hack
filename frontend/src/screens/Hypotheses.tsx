import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt, fxLabel, fxReady } from '../api'
import type { Hypothesis } from '../types'
import {
  Badge, CapexBadge, ChunkModal, EmptyBox, ErrorBox, Icon, Meter, PageHeader, Panel,
  SectionLabel, Spinner,
} from '../components/common'

const AREAS = ['дробление', 'измельчение', 'классификация', 'флотация', 'реагентика', 'вспомогательные']
const W_LABELS: Record<string, string> = {
  money: 'Экономический эффект', capex: 'Стоимость внедрения', risk: 'Риск', novelty: 'Новизна',
}
const W_HINTS: Record<string, string> = {
  money: 'выше вес — выше в списке гипотезы с большим эффектом, ₽/год',
  capex: 'выше вес — выше в списке дешёвые во внедрении',
  risk: 'выше вес — выше в списке менее рискованные',
  novelty: 'выше вес — выше в списке новые для компании',
}

// диагностические правила (backend/app/diagnostics.py). diagnosis_rule гипотезы —
// только R1/R2/R3 («активные» причины); R4 (не предложено) и R5 (аномалии) тегами не бывают.
const RULE_SHORT: Record<string, string> = {
  R1: 'Недоизмельчение', R2: 'Переизмельчение', R3: 'Недоработка флотации',
}
// тултип — только факт диагноза, без предписания (оно у каждой гипотезы своё)
const RULE_TITLES: Record<string, string> = {
  R1: 'R1 · Недоизмельчение: извлекаемый металл заперт в крупных сростках (классы +125, −125+71) — флотация его не раскрывает.',
  R2: 'R2 · Переизмельчение: готовый минерал перемолот в шламы −10 мкм — пузырёк его не удерживает.',
  R3: 'R3 · Недоработка флотации: минерал раскрыт в средних классах, но не выловлен.',
}

const _LMH: Record<string, number> = { low: 0, med: 0.5, medium: 0.5, high: 1 }
const _LMH_RU: Record<string, string> = {
  low: 'низкая', med: 'средняя', medium: 'средняя', high: 'высокая',
}
const _plural = (n: number, one: string, few: string, many: string) =>
  n % 10 === 1 && n % 100 !== 11 ? one
    : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? few : many

/** Нормы критериев — зеркалят формулу бэкенда (rank.py), не LLM:
 *  риск = 0.5·(число рисков/4) + 0.5·сложность; capex по категории. */
function riskNorm(h: Hypothesis): number {
  const compl = _LMH[String(h.feasibility?.complexity ?? 'med').toLowerCase()] ?? 0.5
  return 0.5 * Math.min(h.risks.length / 4, 1) + 0.5 * compl
}
function capexNorm(h: Hypothesis): number {
  return _LMH[String(h.feasibility?.capex ?? 'med').toLowerCase()] ?? 0.5
}
function riskLevel(h: Hypothesis): ['низкий' | 'средний' | 'высокий', 'ok' | 'warn' | 'danger'] {
  const v = riskNorm(h)
  return v < 0.3 ? ['низкий', 'ok'] : v < 0.65 ? ['средний', 'warn'] : ['высокий', 'danger']
}

export default function Hypotheses() {
  const { pid = '' } = useParams()
  const nav = useNavigate()
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

  // после загрузки курса ЦБ перерисовываем суммы в ₽
  const [, setFxTick] = useState(0)
  useEffect(() => { fxReady.then(() => setFxTick(t => t + 1)) }, [])

  // живое пере-ранжирование: слайдеры весов применяются к текущему списку
  // сразу (debounce 450 мс), без регенерации через LLM
  const firstRank = useRef(true)
  const [reranking, setReranking] = useState(false)
  useEffect(() => {
    if (firstRank.current) { firstRank.current = false; return }
    const t = setTimeout(() => {
      setReranking(true)
      api.rerank(pid, weights)
        .then(setHyps)
        .catch(e => setErr(String(e)))
        .finally(() => setReranking(false))
    }, 450)
    return () => clearTimeout(t)
  }, [weights, pid])

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
  // границы нормировки эффекта — по всему списку, как в rank.py
  const [moneyLo, moneyHi] = useMemo(() => {
    const ms = (hyps ?? []).map(h => h.effect.money_usd)
    return ms.length ? [Math.min(...ms), Math.max(...ms)] : [0, 0]
  }, [hyps])

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
    <div className="flex flex-col animate-in" style={{ height: 'calc(100vh - 85px)' }}>
      <PageHeader title="Гипотезы"
        subtitle={`Ранжирование по вашим весам · эффект в ₽ по курсу ${fxLabel()}`}
        actions={
          <button className="btn btn-primary" onClick={() => nav(`/p/${pid}/export`)}>
            К отчёту <Icon name="arrowRight" />
          </button>
        } />

      <div className="flex gap-4 flex-1 min-h-0 mt-4">
        {/* левая панель — статична, скроллится только при нехватке высоты */}
        <aside className="w-64 shrink-0 space-y-4 overflow-y-auto scroll-fade h-full pr-1 pt-1 pb-2">
          <Panel title="Приоритеты ранжирования"
            subtitle={reranking ? 'пересортировка…' : 'действуют сразу, без регенерации'}
            bodyClass="p-4 space-y-3.5">
            {Object.entries(weights).map(([k, v]) => (
              <label key={k} className="block" title={W_HINTS[k]}>
                <span className="field-label">{W_LABELS[k]}</span>
                <span className="num float-right text-muted">{v.toFixed(2)}</span>
                <input type="range" min={0} max={1} step={0.05} value={v}
                  className="w-full mt-1.5 block"
                  onChange={e => setWeights(w => ({ ...w, [k]: Number(e.target.value) }))} />
              </label>
            ))}
            <div className="text-xs pt-1" style={{ color: 'var(--c-faint)' }}>
              Вес — важность критерия в сортировке: дешёвые, менее рисковые
              и новые поднимаются выше.
            </div>
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

        {/* карточки — прокручиваются внутри своей области */}
        <div className="flex-1 min-w-0 space-y-3 overflow-y-auto scroll-fade h-full pr-1 pt-1 pb-2">
          {err && <ErrorBox error={err} />}
          {hyps === null && !err && <Spinner />}
          {hyps !== null && visible.length === 0 &&
            <EmptyBox text="Гипотез пока нет" hint="Нажмите «Сгенерировать гипотезы» слева" icon="flask" />}
          <div className="space-y-3 stagger">
            {visible.map((h, i) => (
              <HypCard key={h.id} h={h} rank={i + 1} onFeedback={feedback}
                weights={weights} moneyLo={moneyLo} moneyHi={moneyHi}
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

/** Разбор оценки: те же числа, что в формуле ранжирования (не LLM). */
function ScoreBreakdown({ h, weights, lo, hi }: {
  h: Hypothesis; weights: Record<string, number>; lo: number; hi: number
}) {
  const moneyN = hi > lo ? (h.effect.money_usd - lo) / (hi - lo) : 0.5
  const novelty = h.novelty?.score ?? 1
  const [riskLbl] = riskLevel(h)
  const rows = [
    { k: 'money', val: moneyN,
      note: `${fmt.rub(h.effect.money_usd)}/год (${fmt.usd(h.effect.money_usd)}) — `
        + `${Math.round(moneyN * 100)}% от максимума в списке` },
    { k: 'capex', val: 1 - capexNorm(h),
      note: { 0: 'внедрение от 100 млн ₽ — дорогое', 0.5: 'внедрение 10–100 млн ₽ — средней стоимости',
        1: 'внедрение до 10 млн ₽ — дешёвое' }[1 - capexNorm(h)] ?? '' },
    { k: 'risk', val: 1 - riskNorm(h),
      note: (() => {
        const compl = String(h.feasibility?.complexity ?? 'med').toLowerCase()
        const interv = compl === 'low' ? 'вмешательство простое и обратимое'
          : compl === 'high' ? 'сложное вмешательство в процесс'
            : 'вмешательство средней сложности'
        return `${interv} → риск внедрения ${riskLbl} `
          + `(${h.risks.length} ${_plural(h.risks.length,
            'технический риск', 'технических риска', 'технических рисков')})`
      })() },
    { k: 'novelty', val: novelty,
      note: novelty >= 0.99 ? 'совпадений с наработками нет' : 'есть наработки — балл снижен' },
  ]
  const penalized = h.rationale.length > 0 && !h.rationale.some(c => c.verified)
  const total = rows.reduce((s, r) => s + (weights[r.k] ?? 0) * r.val, 0) * (penalized ? 0.75 : 1)
  return (
    <div>
      <SectionLabel>Разбор оценки — почему такой ранг</SectionLabel>
      <div className="space-y-1.5">
        {rows.map(r => (
          <div key={r.k} className="flex items-center gap-2.5 text-xs" title={r.note}>
            <span className="w-40 shrink-0 text-muted truncate">{W_LABELS[r.k]}</span>
            <Meter value={r.val} className="w-28 shrink-0" />
            <span className="num w-28 text-right shrink-0">
              {r.val.toFixed(2)} × вес {(weights[r.k] ?? 0).toFixed(2)}
            </span>
            <span className="num w-16 text-right font-semibold shrink-0">
              = {((weights[r.k] ?? 0) * r.val).toFixed(3)}
            </span>
            <span className="text-faint truncate flex-1 min-w-0">{r.note}</span>
          </div>
        ))}
        <div className="flex items-center gap-2.5 text-xs pt-1 border-t border-line">
          <span className="w-40 shrink-0 text-muted">
            {penalized ? 'штраф ×0.75 — нет подтверждённых цитат' : 'итог'}
          </span>
          <span className="num font-bold">score ≈ {total.toFixed(3)}</span>
        </div>
      </div>
      <div className="text-xs mt-1.5" style={{ color: 'var(--c-faint)' }}>
        Оценка — детерминированная формула (вклад = значение × вес, эффект
        нормирован по текущему списку), а не мнение модели.
      </div>
    </div>
  )
}

function HypCard({ h, rank, onFeedback, onChunk, weights, moneyLo, moneyHi }: {
  h: Hypothesis; rank: number
  onFeedback: (h: Hypothesis, a: 'accept' | 'reject') => void
  onChunk: (id: string, quote: string) => void
  weights: Record<string, number>; moneyLo: number; moneyHi: number
}) {
  const [open, setOpen] = useState(rank === 1)
  const missing = h.equipment.filter(e => !e.present_on_plant)
  const present = h.equipment.filter(e => e.present_on_plant)
  const [riskLbl, riskTone] = riskLevel(h)
  // новизна: совпадений нет — новое для компании; есть — компания уже имеет
  // наработки по теме (гипотезы экспертов института или принятые ранее)
  const matches = (h.novelty?.prior_matches ?? []).filter(m => m !== h.title)
  const hasPrior = matches.length > 0

  const accent = h.status === 'accepted'
    ? { borderLeft: '4px solid var(--c-ok)', background: 'color-mix(in srgb, var(--c-ok) 6%, var(--c-surface))' }
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
            <Badge tone={riskTone} title={h.risks.length ? `Риски: ${h.risks.join('; ')}` : 'Рисков не указано'}>
              риск {riskLbl}
            </Badge>
            {hasPrior ? (
              <Badge title={`Совпадает с наработками: ${matches.join('; ')}`}>
                есть наработки в компании
              </Badge>
            ) : (
              <Badge tone="brand">новое для компании</Badge>
            )}
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
            {h.diagnosis_rule && (
              <Badge title={RULE_TITLES[h.diagnosis_rule]
                ?? `Диагноз ${h.diagnosis_rule} — из него выросла гипотеза`}>
                <span className="num">[{h.diagnosis_rule}]</span>
                {RULE_SHORT[h.diagnosis_rule] ? ` ${RULE_SHORT[h.diagnosis_rule]}` : ' диагноз'}
              </Badge>
            )}
            {h.uncertain && <Badge tone="warn">оценка на непроверенных данных</Badge>}
            {h.status === 'accepted' && <Badge tone="solid">принята</Badge>}
            {h.status === 'rejected' && <Badge tone="danger">отклонена</Badge>}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="num font-semibold">до {fmt.t(h.effect.tonnes_expected, 0)} т {h.element}/год</div>
          <div className="num text-sm text-muted">≈ {fmt.rub(h.effect.money_usd)}/год</div>
          <div className="num text-xs" style={{ color: 'var(--c-faint)' }}>{fmt.usd(h.effect.money_usd)}/год</div>
          <Meter value={h.score} title={`score ${h.score.toFixed(3)}`} className="w-28 ml-auto mt-1.5" />
        </div>
      </div>

      {open && (
        <div className="px-3 pb-3 pt-3 border-t border-line space-y-3">
          <p className="text-sm leading-relaxed">{h.mechanism}</p>

          <ScoreBreakdown h={h} weights={weights} lo={moneyLo} hi={moneyHi} />

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

          <div className="flex gap-2 pt-3 border-t border-line items-center flex-wrap">
            {h.status === 'accepted' ? (<>
              <span className="badge badge-ok"><Icon name="check" className="w-3.5 h-3.5" />Принята</span>
              <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); onFeedback(h, 'reject') }}>
                <Icon name="x" />Передумать — отклонить
              </button>
            </>) : h.status === 'rejected' ? (<>
              <span className="badge badge-danger"><Icon name="x" className="w-3.5 h-3.5" />Отклонена</span>
              <button className="btn btn-ok btn-sm" onClick={e => { e.stopPropagation(); onFeedback(h, 'accept') }}>
                <Icon name="check" />Всё-таки принять
              </button>
            </>) : (<>
              <button className="btn btn-ok" onClick={e => { e.stopPropagation(); onFeedback(h, 'accept') }}>
                <Icon name="check" />Принять
              </button>
              <button className="btn btn-danger" onClick={e => { e.stopPropagation(); onFeedback(h, 'reject') }}>
                <Icon name="x" />Отклонить…
              </button>
            </>)}
            <span className="ml-auto num text-xs text-faint self-center">
              score {h.score.toFixed(3)} · id {h.id}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
