import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { FlowsheetData, FlowsheetNode } from '../types'
import { Icon, Modal, SectionLabel } from './common'

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

/** Попап перед загрузкой схемы: что произойдёт и сколько займёт. */
function DigitizeInfoModal({ onPick, onClose }: { onPick: () => void; onClose: () => void }) {
  return (
    <Modal title="Оцифровка схемы фабрики" onClose={onClose}>
      <div className="space-y-3 text-sm leading-relaxed">
        <p>
          Загрузите изображение схемы цепи аппаратов или режимной карты
          (png/jpg). Дальше автоматически:
        </p>
        <ol className="list-decimal ml-5 space-y-1">
          <li><b>OCR подписей</b> (Yandex Vision) — узлы, времена, % твёрдого,
            реагенты с расходами · <span className="num">~5–10 сек</span>;</li>
          <li><b>Сборка структуры</b> — модель собирает узлы и потоки в схему
            · <span className="num">~1–2 мин</span>, идёт в фоне.</li>
        </ol>
        <p className="text-xs" style={{ color: 'var(--c-faint)' }}>
          Результат — черновик: стрелки на изображении OCR не видит, поэтому
          последовательность операций восстанавливается по подписям (сверху
          вниз). Проверьте итог кнопкой «Схема фабрики» — оцифрованная схема
          сразу учитывается в диагнозах и генерации гипотез этой линии.
        </p>
        <div className="flex justify-end gap-2 pt-1">
          <button className="btn" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={onPick}>
            <Icon name="upload" className="w-4 h-4" /> Выбрать изображение
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** Текстовая схема фабрики в карточке линии: свёрнута по умолчанию; кнопка
 * загрузки изображения с фоновой оцифровкой (OCR + LLM) и поллингом статуса. */
export default function FlowsheetText({ lineId, lineName }: { lineId: string; lineName: string }) {
  const key = factoryOfLine(lineName) ?? lineId
  const [open, setOpen] = useState(false)
  const [fs, setFs] = useState<FlowsheetData | null>(null)
  const [source, setSource] = useState<'case' | 'upload' | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'none' | 'processing' | 'failed'>('idle')
  const [failReason, setFailReason] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const fetchFs = () => {
    setState('loading')
    api.factoryFlowsheet(key)
      .then(r => {
        if (r.status === 'processing') { setState('processing'); return }
        if (r.status === 'failed') { setState('failed'); setFailReason(r.error ?? ''); return }
        setFs(r.flowsheet); setSource((r.source as 'case' | 'upload') ?? 'case'); setState('idle')
      })
      .catch(() => setState('none'))
  }

  useEffect(() => { setOpen(false); setFs(null); setState('idle') }, [lineId])
  useEffect(() => {
    if (open && !fs && state !== 'processing') fetchFs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // пока идёт оцифровка — поллим статус
  useEffect(() => {
    if (state !== 'processing') return
    const t = setInterval(fetchFs, 5000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state])

  const uploadScheme = async (file: File) => {
    setUploading(true)
    try {
      await api.lineFlowsheetUpload(lineId, file)
      setFs(null); setOpen(true); setState('processing')
    } catch (e) {
      setState('failed'); setFailReason(String(e))
    } finally { setUploading(false) }
  }

  const tails = new Set((fs?.streams ?? []).filter(s => s.kind === 'tails').map(s => s.from))
  const groups = fs
    ? TYPE_ORDER.map(t => ({ type: t, nodes: fs.nodes.filter(n => n.type === t) }))
        .filter(g => g.nodes.length > 0)
    : []

  return (
    <div>
      <div className="flex items-center gap-3 flex-wrap">
        <button type="button"
          className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted hover:text-brand cursor-pointer"
          title={open ? 'Свернуть схему' : 'Показать, как схема оцифрована'}
          onClick={() => setOpen(v => !v)}>
          <Icon name="arrowRight" strokeWidth={2.5}
            className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-90' : ''}`} />
          Схема фабрики{factoryOfLine(lineName) ? ` (${factoryOfLine(lineName)})` : ''}
          {!open && <span className="normal-case font-normal text-faint">— показать</span>}
        </button>
        <button type="button"
          className="text-xs text-brand hover:underline underline-offset-2 cursor-pointer"
          title="Загрузить изображение схемы — оно будет оцифровано и учтено в диагнозах и генерации"
          onClick={() => setInfoOpen(true)} disabled={uploading}>
          {uploading ? 'загружаю…' : state === 'processing' ? 'оцифровываем…' : 'загрузить схему'}
        </button>
        {source === 'upload' && fs && (
          <span className="badge badge-warn">оцифровано из загрузки — черновик, проверьте</span>
        )}
      </div>
      <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp,.bmp" className="hidden"
        onChange={e => e.target.files?.[0] && uploadScheme(e.target.files[0])} />

      {open && (
        <div className="mt-2 animate-in">
          {state === 'loading' && <div className="text-sm text-faint">Загружаю схему…</div>}
          {state === 'processing' && (
            <div className="text-sm inline-flex items-center gap-2 text-brand">
              <span className="inline-block w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
              Оцифровываем: OCR подписей + сборка структуры (~1–2 мин)…
            </div>
          )}
          {state === 'failed' && (
            <div className="text-sm text-danger">
              Оцифровка не удалась: {failReason || 'неизвестная ошибка'} — попробуйте
              другое изображение (чётче подписи).
            </div>
          )}
          {state === 'none' && (
            <div className="text-sm text-faint">
              Схема этой фабрики не оцифрована — загрузите изображение кнопкой
              «загрузить схему».
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

      {infoOpen && (
        <DigitizeInfoModal onClose={() => setInfoOpen(false)}
          onPick={() => { setInfoOpen(false); fileRef.current?.click() }} />
      )}
    </div>
  )
}
