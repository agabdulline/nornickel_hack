import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, KbDoc, Line, LineKind, LineMaterial, Material, LineOwnership, StopEntry } from '../types'
import { Badge, ChunkModal, ErrorBox, Icon, Modal, Panel, SectionLabel, Segmented, reflowPdfText } from '../components/common'
import {
  commitLineEdits, type DraftEquipment, type DraftMaterial, EquipmentRows, MaterialRows,
  toDraftEquipment, toDraftMaterial,
} from '../components/lines'
import FactoryImages from '../components/FactoryImages'

const KIND_OPTIONS: LineKind[] = ['производственная линия', 'лаборатория']
const OWNERSHIP_OPTIONS: LineOwnership[] = ['в штате компании', 'внешний подрядчик/партнёр']

/** Раздел «Фабрики и лаборатории»: те же мастер-данные, что и в форме проекта
 * (write-through) — два входа в одни и те же записи, а не два разных набора.
 *
 * Одна кнопка «Изменить» переключает всю карточку целиком: название и состав
 * (оборудование, сырьё) редактируются одновременно, staged локально, и
 * коммитятся на бэкенд одним пакетом по «Сохранить» — «Отмена» ничего не
 * трогает, поскольку до сохранения запросов на запись не было. */
function LinesSection() {
  const [lines, setLines] = useState<Line[]>([])
  const [materialsCatalog, setMaterialsCatalog] = useState<Material[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [equipment, setEquipment] = useState<Equipment[]>([])
  const [materials, setMaterials] = useState<LineMaterial[]>([])
  const [stoplist, setStoplist] = useState<StopEntry[]>([])
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState<LineKind>('производственная линия')

  const [editingLineId, setEditingLineId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftKind, setDraftKind] = useState<LineKind>('производственная линия')
  const [draftOwnership, setDraftOwnership] = useState<LineOwnership>('в штате компании')
  const [draftEquipment, setDraftEquipment] = useState<DraftEquipment[]>([])
  const [draftMaterials, setDraftMaterials] = useState<DraftMaterial[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => { api.lines().then(setLines) }, [])
  useEffect(() => { api.materials().then(setMaterialsCatalog).catch(() => setMaterialsCatalog([])) }, [])

  const fetchLineData = async (line: Line) => {
    const [eq, mats, stop] = await Promise.all([
      api.equipmentForLine(line.id), api.lineMaterials(line.id), api.lineStoplist(line.id),
    ])
    setEquipment(eq); setMaterials(mats); setStoplist(stop)
    return { eq, mats, stop }
  }

  const deleteStop = async (line: Line, id: string) => {
    setStoplist(prev => prev.filter(s => s.id !== id))   // оптимистично
    try { await api.deleteLineStop(id) }
    catch { fetchLineData(line) }                        // откат — перечитать
  }

  const toggleExpand = async (line: Line) => {
    if (expanded === line.id) { setExpanded(null); setEditingLineId(null); return }
    setEditingLineId(null)
    setExpanded(line.id)
    await fetchLineData(line)
  }

  const createLine = async () => {
    if (!newName.trim()) return
    const line = await api.createLine({ name: newName.trim(), kind: newKind })
    setLines(prev => [...prev, line].sort((a, b) => a.name.localeCompare(b.name)))
    setNewName(''); setNewKind('производственная линия'); setCreating(false)
  }

  const startEdit = async (line: Line) => {
    let eq = equipment, mats = materials
    if (expanded !== line.id) {
      setExpanded(line.id)
      const fetched = await fetchLineData(line)
      eq = fetched.eq; mats = fetched.mats
    }
    setDraftName(line.name); setDraftKind(line.kind); setDraftOwnership(line.ownership)
    setDraftEquipment(toDraftEquipment(eq)); setDraftMaterials(toDraftMaterial(mats))
    setEditingLineId(line.id)
  }

  const cancelEdit = () => setEditingLineId(null)

  const saveEdit = async (line: Line) => {
    setSaving(true)
    try {
      let updatedLine = line
      if (draftName.trim() && (draftName !== line.name || draftKind !== line.kind || draftOwnership !== line.ownership)) {
        updatedLine = await api.updateLine(line.id, {
          name: draftName.trim(), kind: draftKind, ownership: draftOwnership,
        })
      }
      const fresh = await commitLineEdits(line.id,
        { equipment, materials },
        { equipment: draftEquipment, materials: draftMaterials })
      setLines(prev => prev.map(l => l.id === line.id ? updatedLine : l).sort((a, b) => a.name.localeCompare(b.name)))
      setEquipment(fresh.equipment); setMaterials(fresh.materials)
      setEditingLineId(null)
    } finally { setSaving(false) }
  }

  return (
    <Panel
      title="Фабрики и лаборатории"
      subtitle="Мастер-данные объектов: оборудование и сырьё для проверки гипотез"
      bodyClass="p-4 space-y-3"
      actions={
        <button className="btn btn-sm" onClick={() => setCreating(v => !v)}>
          <Icon name="plus" className="w-4 h-4" />Новая линия/лаборатория
        </button>
      }
    >
      {creating && (
        <div className="flex flex-wrap gap-1.5 items-center bg-surface-2 border border-line rounded-md p-2 animate-in">
          <input className="input flex-1 min-w-40"
            placeholder="напр.: НОФ · медистые руды"
            value={newName} onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createLine() } }} />
          <select className="select w-56"
            value={newKind} onChange={e => setNewKind(e.target.value as LineKind)}>
            {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
          <button className="btn btn-primary shrink-0" disabled={!newName.trim()} onClick={createLine}>Создать</button>
        </div>
      )}

      <div className="divide-y divide-line">
        {lines.map(line => {
          const isEditing = editingLineId === line.id
          const isExpanded = expanded === line.id
          return (
            <div key={line.id} className="py-2">
              <div className="flex items-center justify-between gap-2">
                {isEditing ? (
                  <div className="flex flex-wrap gap-1.5 items-center flex-1">
                    <input className="input flex-1 min-w-40"
                      placeholder="напр.: НОФ · вкрапленные руды"
                      value={draftName} onChange={e => setDraftName(e.target.value)} />
                    <select className="select w-56"
                      value={draftKind} onChange={e => setDraftKind(e.target.value as LineKind)}>
                      {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
                    </select>
                    <select className="select w-64"
                      value={draftOwnership} onChange={e => setDraftOwnership(e.target.value as LineOwnership)}>
                      {OWNERSHIP_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                ) : (
                  <button type="button" aria-expanded={isExpanded}
                    className="group flex items-center gap-2 text-left flex-1 min-w-0 -ml-1.5 px-1.5 py-1 rounded-md hover:bg-surface-2 transition-colors"
                    onClick={() => toggleExpand(line)}>
                    <Icon name="arrowRight" strokeWidth={2.5}
                      className={`w-4 h-4 shrink-0 text-faint transition-transform duration-200 ${isExpanded ? 'rotate-90' : ''}`} />
                    <span className="font-medium text-base truncate">{line.name}</span>
                    {line.ownership === 'внешний подрядчик/партнёр' && (
                      <Badge tone="brand">внешний партнёр</Badge>
                    )}
                    <Badge tone={line.kind === 'лаборатория' ? 'warn' : 'default'}>{line.kind}</Badge>
                  </button>
                )}
                <div className="flex items-center gap-2 shrink-0">
                  {isEditing ? (
                    <>
                      <button type="button" className="btn btn-primary btn-sm" disabled={saving}
                        onClick={() => saveEdit(line)}>Сохранить</button>
                      <button type="button" className="btn btn-sm" disabled={saving} onClick={cancelEdit}>Отмена</button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-ghost btn-sm text-brand"
                      onClick={() => startEdit(line)}>Изменить</button>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="mt-2 ml-6 pl-3 border-l-2 border-line space-y-3 animate-in">
                  {isEditing ? (
                    <>
                      <EquipmentRows rows={draftEquipment} onChange={setDraftEquipment} />
                      <MaterialRows rows={draftMaterials} onChange={setDraftMaterials} catalog={materialsCatalog} />
                    </>
                  ) : (
                    <>
                      <div>
                        <SectionLabel>Оборудование объекта</SectionLabel>
                        {equipment.length === 0 && (
                          <div className="text-sm text-faint">
                            Оборудование не указано — добавьте его через «Изменить».
                          </div>
                        )}
                        <div className="flex flex-wrap gap-1.5">
                          {equipment.map(e => (
                            <Badge key={e.id}>{e.name}{e.position && ` (${e.position})`}</Badge>
                          ))}
                        </div>
                      </div>
                      <div>
                        <SectionLabel>Сырьё</SectionLabel>
                        {materials.length === 0 && (
                          <div className="text-sm text-faint">Сырьё для этого объекта ещё не заведено.</div>
                        )}
                        <div className="flex flex-wrap gap-1.5">
                          {materials.map(m => (
                            <Badge key={m.id} tone="brand">
                              {m.name} — {m.quantity.toLocaleString('ru-RU')} {m.unit}
                            </Badge>
                          ))}
                        </div>
                      </div>
                      <div>
                        <SectionLabel>Стоп-лист линии</SectionLabel>
                        {stoplist.length === 0 ? (
                          <div className="text-sm text-faint">
                            Отклонённых направлений пока нет — они накапливаются, когда
                            эксперт отклоняет гипотезу на любом проекте этой линии, и
                            исключаются при следующей генерации.
                          </div>
                        ) : (
                          <div className="space-y-1.5">
                            {stoplist.map(s => (
                              <div key={s.id}
                                className="flex items-start justify-between gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2">
                                <div className="min-w-0">
                                  <div className="text-sm text-text font-medium">{s.direction || '—'}</div>
                                  {s.reason && (
                                    <div className="text-xs text-muted mt-0.5">Причина: {s.reason}</div>
                                  )}
                                  {s.created_at && (
                                    <div className="num text-[11px] text-faint mt-0.5">
                                      отклонено {new Date(s.created_at).toLocaleDateString('ru-RU')}
                                    </div>
                                  )}
                                </div>
                                <button type="button"
                                  className="btn btn-ghost btn-sm text-danger px-1.5 shrink-0"
                                  title="Убрать из стоп-листа — направление снова сможет предлагаться"
                                  onClick={() => deleteStop(line, s.id)}>
                                  <Icon name="trash" className="w-4 h-4" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {lines.length === 0 && (
          <div className="text-faint text-sm text-center py-4">Пока нет ни одной линии/лаборатории.</div>
        )}
      </div>
    </Panel>
  )
}

const LANGS = ['ru', 'en', 'zh'] as const
type LangTab = 'all' | (typeof LANGS)[number]
const LANG_LABEL: Record<string, string> = { ru: 'Русский', en: 'English', zh: '中文' }
// неизвестный код языка не должен прятать документ — считаем русским
const langOf = (d: KbDoc) => (LANGS as readonly string[]).includes(d.lang ?? '') ? d.lang! : 'ru'

// порядок тем в таблице; неизвестная тема падает в «прочее»
const TOPIC_ORDER = ['флотация', 'измельчение и классификация', 'дробление',
  'металлургия благородных металлов', 'прочее']
const topicOf = (d: KbDoc) => TOPIC_ORDER.includes(d.topic ?? '') ? d.topic! : 'прочее'

/** Модалка-читалка источника: вкладки «Текст» (чанки постранично) и
 * «Исходник» (оригинальный PDF/TXT во встроенном просмотрщике). */
function DocPreviewModal({ doc, onClose }: { doc: KbDoc; onClose: () => void }) {
  const [chunks, setChunks] = useState<{ chunk_id: string; page_start: number; page_end: number; text: string }[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [hasFile, setHasFile] = useState(false)
  const [mode, setMode] = useState<'text' | 'ru' | 'file'>('text')
  const [ru, setRu] = useState<Record<string, string>>({})
  const [ruBusy, setRuBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const foreign = langOf(doc) !== 'ru'

  const load = (offset: number) => {
    setLoading(true)
    api.kbDocPreview(doc.doc_id, offset, 6)
      .then(r => {
        setChunks(prev => offset === 0 ? r.chunks : [...prev, ...r.chunks])
        setTotal(r.total_chunks); setHasFile(r.has_file ?? false)
      })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load(0) }, [doc.doc_id])

  // перевод видимых фрагментов — лениво, батчем, с серверным кэшем
  useEffect(() => {
    if (mode !== 'ru' || ruBusy) return
    const missing = chunks.filter(c => !(c.chunk_id in ru)).map(c => c.chunk_id)
    if (missing.length === 0) return
    setRuBusy(true)
    api.kbTranslate(missing.slice(0, 12))
      .then(r => setRu(prev => ({ ...prev, ...r.translations })))
      .catch(e => setErr(String(e)))
      .finally(() => setRuBusy(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, chunks])

  const tabs: { value: 'text' | 'ru' | 'file'; label: string }[] = [
    { value: 'text', label: foreign ? 'Оригинал' : 'Текст' },
    ...(foreign ? [{ value: 'ru' as const, label: 'По-русски' }] : []),
    ...(hasFile ? [{ value: 'file' as const, label: 'Исходник' }] : []),
  ]
  return (
    <Modal wide onClose={onClose}
      title={<span className="inline-flex items-center gap-3">
        <span className="truncate">{doc.source}</span>
        <span className="num text-faint font-normal shrink-0">{doc.pages} стр. · {doc.chunks} фрагм.</span>
        {tabs.length > 1 && <Segmented options={tabs} value={mode} onChange={setMode} />}
      </span>}>
      {err && <ErrorBox error={err} />}
      {mode === 'file' && hasFile ? (
        <iframe title={`Исходник: ${doc.source}`}
          src={`/api/kb/documents/${encodeURIComponent(doc.doc_id)}/file`}
          className="w-full rounded-md border border-line bg-white"
          style={{ height: '68vh' }} />
      ) : (
        <div className="space-y-4">
          {mode === 'ru' && (
            <div className="text-[11px]" style={{ color: 'var(--c-faint)' }}>
              Машинный перевод — термины и числа сверяйте с оригиналом.
            </div>
          )}
          {chunks.map(c => (
            <div key={c.chunk_id}>
              <div className="num text-xs text-faint mb-1">
                с. {c.page_start}{c.page_end !== c.page_start ? `–${c.page_end}` : ''}
              </div>
              <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--c-text)' }}>
                {mode === 'ru'
                  ? (ru[c.chunk_id] ?? (ruBusy
                      ? <span className="inline-flex items-center gap-2 text-faint">
                          <span className="inline-block w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />
                          Переводим…
                        </span>
                      : <span className="text-faint">Перевод не получен.</span>))
                  : reflowPdfText(c.text)}
              </div>
            </div>
          ))}
          {total === 0 && !loading &&
            <div className="text-faint text-sm">Текста нет — скан без распознанного слоя.</div>}
          {total !== null && chunks.length < total && (
            <button className="btn btn-sm" disabled={loading} onClick={() => load(chunks.length)}>
              {loading
                ? <span className="inline-block w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
                : <>Показать ещё <span className="num">({chunks.length}/{total})</span></>}
            </button>
          )}
        </div>
      )}
    </Modal>
  )
}

/** Тумблер «участвует ли источник в поиске» — с подписью, а не голая галочка. */
function SearchSwitch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={onToggle}
      className="inline-flex items-center gap-2 cursor-pointer select-none"
      title={on ? 'Источник участвует в поиске и цитатах гипотез. Нажмите, чтобы временно исключить.'
               : 'Источник исключён: не участвует в поиске и новых цитатах. Нажмите, чтобы включить обратно.'}>
      <span className="relative inline-block w-[34px] h-[18px] rounded-full transition-colors"
        style={{ background: on ? 'var(--c-brand)' : 'var(--c-line)' }}>
        <span className="absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-all"
          style={{ left: on ? '18px' : '2px', boxShadow: '0 1px 2px rgba(0,0,0,.25)' }} />
      </span>
      <span className={`text-xs whitespace-nowrap ${on ? 'text-brand font-medium' : 'text-faint'}`}>
        {on ? 'в поиске' : 'выключен'}
      </span>
    </button>
  )
}

function DocStatus({ d }: { d: KbDoc }) {
  if (d.status === 'indexed')
    return <Badge tone="ok"><Icon name="check" className="w-3 h-3" /> индексирован</Badge>
  if (d.status === 'indexed_ocr')
    return (
      <Badge tone="ok" title="Скан распознан Yandex Vision OCR и проиндексирован">
        <Icon name="check" className="w-3 h-3" /> распознан (OCR)
      </Badge>
    )
  if (d.status === 'ocr_processing') {
    const pct = d.pages ? Math.round(((d.ocr_done ?? 0) / d.pages) * 100) : 0
    return (
      <Badge tone="brand">
        <span className="inline-block w-3 h-3 rounded-full border-2 border-brand border-t-transparent animate-spin" />
        распознаём… <span className="num">{d.ocr_done ?? 0}/{d.pages} ({pct}%)</span>
      </Badge>
    )
  }
  if (d.status === 'ocr_failed')
    return <Badge tone="danger" title={d.error}><Icon name="x" className="w-3 h-3" /> OCR не удался</Badge>
  return (
    <Badge tone="warn" title="Скан без текстового слоя — в поиске не участвует">
      <Icon name="alert" className="w-3 h-3" /> требуется OCR
    </Badge>
  )
}

/** Попап перед загрузкой: сколько займёт индексация и на чём построен поиск. */
function UploadInfoModal({ onPick, onClose }: { onPick: () => void; onClose: () => void }) {
  const Row = ({ kind, time, note }: { kind: string; time: string; note?: string }) => (
    <tr>
      <td className="py-1 pr-3">{kind}</td>
      <td className="py-1 pr-3 num font-semibold whitespace-nowrap">{time}</td>
      <td className="py-1 text-faint">{note}</td>
    </tr>
  )
  return (
    <Modal title="Загрузка источника в базу знаний" onClose={onClose}>
      <div className="space-y-4 text-sm leading-relaxed">
        <div>
          <SectionLabel>Сколько займёт индексация</SectionLabel>
          <table className="w-full text-sm">
            <tbody>
              <Row kind="Статья (5–20 стр)" time="~0.5–1 мин" />
              <Row kind="Книга 100 стр" time="~5–6 мин" note="вкладку не закрывать" />
              <Row kind="Книга 200 стр" time="~10–12 мин" note="вкладку не закрывать" />
              <Row kind="Скан без текста" time="+~1 стр/сек"
                note="распознавание идёт фоном, прогресс в списке" />
              <Row kind="Английский / китайский" time="+ перевод фоном"
                note="вкладка «По-русски» появится через пару минут" />
            </tbody>
          </table>
          <div className="text-xs text-faint mt-1.5">
            Время уходит на векторизацию фрагментов (~2 с/фрагмент на CPU сервера);
            разбор PDF — секунды.
          </div>
        </div>
        <div>
          <SectionLabel>Как устроен поиск</SectionLabel>
          <p>
            Эмбеддинги — <b>BAAI/bge-m3</b> (открытая мультиязычная модель,
            1024-мерные вектора), гибрид с BM25 по точным терминам. Почему она:
          </p>
          <ul className="list-disc ml-5 mt-1.5 space-y-1">
            <li><b>Локальная</b> — база знаний не зависит от внешних API
              (проверено на практике: облачный эмбеддинг-сервис в один из дней
              лежал, наш поиск не заметил);</li>
            <li><b>Кросс-языковая</b> — русский запрос находит английские и
              китайские источники без перевода (100+ языков);</li>
            <li><b>Бесплатная и без лимитов</b> — индексировать можно
              тысячи документов.</li>
          </ul>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button className="btn" onClick={onClose}>Отмена</button>
          <button className="btn btn-primary" onClick={onPick}>
            <Icon name="upload" className="w-4 h-4" /> Выбрать файл
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function KB() {
  const [docs, setDocs] = useState<KbDoc[]>([])
  const [err, setErr] = useState('')
  const [uploading, setUploading] = useState(false)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<{
    answer: string
    citations: { chunk_id: string; source: string; page: number; quote: string }[]
  } | null>(null)
  const [chunk, setChunk] = useState<string | null>(null)
  const [preview, setPreview] = useState<KbDoc | null>(null)
  const [langTab, setLangTab] = useState<LangTab>('all')
  const [docQuery, setDocQuery] = useState('')
  // темы свёрнуты по умолчанию — раскрываются кликом («подробнее»)
  const [openTopics, setOpenTopics] = useState<Set<string>>(new Set())
  const [uploadInfo, setUploadInfo] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => api.kbDocs().then(setDocs).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  // пока идёт распознавание скана — поллим прогресс
  const ocrActive = docs.some(d => d.status === 'ocr_processing')
  useEffect(() => {
    if (!ocrActive) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [ocrActive])

  const upload = async (file: File) => {
    setUploading(true); setErr('')
    try { await api.kbUpload(file); load() }
    catch (e) { setErr(String(e)) } finally { setUploading(false) }
  }

  const toggleDoc = async (d: KbDoc) => {
    const next = !(d.enabled !== false)
    // оптимистично, затем подтверждаем ответом бэкенда
    setDocs(prev => prev.map(x => x.doc_id === d.doc_id ? { ...x, enabled: next } : x))
    try { await api.kbSetEnabled(d.doc_id, next) }
    catch (e) { setErr(String(e)); load() }
  }

  // тумблер целой темы: если хоть один включён — выключаем все, иначе включаем все
  const toggleTopic = async (group: KbDoc[]) => {
    const next = !group.some(d => d.enabled !== false)
    const ids = new Set(group.map(d => d.doc_id))
    setDocs(prev => prev.map(x => ids.has(x.doc_id) ? { ...x, enabled: next } : x))
    try { await Promise.all(group.map(d => api.kbSetEnabled(d.doc_id, next))) }
    catch (e) { setErr(String(e)); load() }
  }

  const deleteDoc = async (d: KbDoc) => {
    if (!window.confirm(`Удалить источник «${d.source}» из базы знаний?\n`
      + 'Чанки и векторы будут удалены безвозвратно; цитаты уже созданных '
      + 'гипотез из этого источника перестанут открываться.')) return
    try { await api.kbDelete(d.doc_id); load() }
    catch (e) { setErr(String(e)) }
  }

  const ask = async () => {
    if (!question.trim()) return
    setAsking(true); setAnswer(null)
    try { setAnswer(await api.kbAsk(question)) }
    catch (e) { setErr(String(e)) } finally { setAsking(false) }
  }

  const q = docQuery.trim().toLowerCase()
  const matchesQuery = (d: KbDoc) =>
    !q || d.source.toLowerCase().includes(q) || topicOf(d).toLowerCase().includes(q)
  const tabDocs = docs.filter(d => (langTab === 'all' || langOf(d) === langTab) && matchesQuery(d))
  const tabCount = (t: LangTab) =>
    t === 'all' ? docs.length : docs.filter(d => langOf(d) === t).length

  const toggleTopicOpen = (topic: string) =>
    setOpenTopics(prev => {
      const next = new Set(prev)
      if (next.has(topic)) next.delete(topic)
      else next.add(topic)
      return next
    })

  return (
    <div className="space-y-4">
      <LinesSection />
      <FactoryImages />
      {err && <ErrorBox error={err} />}

      <Panel title="Вопрос к базе знаний"
        subtitle="Ответ строится только по проиндексированным документам, с цитатами и страницами">
        <div className="flex gap-2">
          <input className="input flex-1"
            placeholder="напр.: как извлекают золото из упорных руд?"
            value={question} onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && ask()} />
          <button className="btn btn-primary shrink-0" disabled={asking} onClick={ask}>
            {asking
              ? <span className="inline-block w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
              : <><Icon name="search" className="w-4 h-4" />Спросить</>}
          </button>
        </div>
      </Panel>

      {answer && (
        <div className="card p-4 space-y-3 animate-in">
          <div className="text-sm whitespace-pre-wrap leading-relaxed text-text">{answer.answer}</div>
          {answer.citations.length > 0 && (
            <div className="border-t border-line pt-3">
              <SectionLabel>Источники</SectionLabel>
              <div className="grid md:grid-cols-2 gap-1.5 stagger">
                {answer.citations.map((c, i) => (
                  <button key={i}
                    className="block text-left w-full text-xs rounded-md p-2.5 bg-surface-2 border border-line transition-colors hover:border-brand hover:bg-brand-tint cursor-pointer"
                    onClick={() => setChunk(c.chunk_id)}>
                    <span className="text-text">«{c.quote.slice(0, 140)}…»</span>
                    <span className="num text-muted"> — {c.source}, с. {c.page}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <Panel
        title="Документы"
        subtitle="Источники цитат для гипотез: клик по названию — читать; тумблер «в поиске» временно исключает источник"
        bodyClass="p-0"
        actions={
          <>
            <input className="input h-8 w-52 text-sm"
              placeholder="Поиск по книгам и темам…"
              value={docQuery} onChange={e => setDocQuery(e.target.value)} />
            <Segmented
              options={(['all', ...LANGS] as LangTab[]).map(t => ({
                value: t,
                label: <span>{t === 'all' ? 'Все' : LANG_LABEL[t]}{' '}
                  <span className="num opacity-60">{tabCount(t)}</span></span>,
              }))}
              value={langTab} onChange={setLangTab} />
            <button className="btn btn-primary btn-sm" disabled={uploading}
              onClick={() => setUploadInfo(true)}>
              <Icon name="upload" className="w-4 h-4" />
              {uploading ? 'Индексирую…' : 'Загрузить PDF/TXT'}
            </button>
            <input ref={fileRef} type="file" accept=".pdf,.txt" className="hidden"
              onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
          </>
        }
      >
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th title="Участвует ли источник в поиске и цитатах гипотез">В поиске</th>
                <th>Источник</th>
                <th>Язык</th>
                <th className="text-right">Стр.</th>
                <th className="text-right">Фрагментов</th>
                <th>Статус</th>
                <th className="w-8"></th>
              </tr>
            </thead>
            {TOPIC_ORDER.map(topic => {
              const group = tabDocs.filter(d => topicOf(d) === topic)
              if (group.length === 0) return null
              const active = group.filter(d => d.enabled !== false).length
              // при активном поиске секции раскрыты, чтобы совпадения были видны
              const opened = q !== '' || openTopics.has(topic)
              return (
                <tbody key={topic} className="stagger">
                  <tr className="bg-surface-2/60">
                    <td colSpan={7} className="py-1.5">
                      <span className="inline-flex items-center gap-3">
                        <button type="button"
                          className="inline-flex items-center gap-1.5 cursor-pointer group"
                          title={opened ? 'Свернуть тему' : 'Показать книги темы'}
                          onClick={() => toggleTopicOpen(topic)}>
                          <Icon name="arrowRight" strokeWidth={2.5}
                            className={`w-3.5 h-3.5 text-faint transition-transform duration-200 ${opened ? 'rotate-90' : ''}`} />
                          <span className="text-xs font-semibold uppercase tracking-wide text-muted group-hover:text-brand">{topic}</span>
                        </button>
                        <span className="num text-xs text-faint">{active}/{group.length} в поиске</span>
                        <button type="button"
                          className="text-xs text-brand hover:underline underline-offset-2 cursor-pointer"
                          title="Включить или выключить все источники темы — подборка под кейс"
                          onClick={() => toggleTopic(group)}>
                          {active > 0 ? 'выключить тему' : 'включить тему'}
                        </button>
                        {!opened && (
                          <button type="button"
                            className="text-xs text-faint hover:text-brand cursor-pointer"
                            onClick={() => toggleTopicOpen(topic)}>
                            подробнее…
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                  {opened && group.map(d => {
                    const on = d.enabled !== false
                    return (
                      <tr key={d.doc_id} className={on ? '' : 'opacity-55'}>
                        <td><SearchSwitch on={on} onToggle={() => toggleDoc(d)} /></td>
                        <td className="max-w-md">
                          <button type="button"
                            className="text-left truncate max-w-full hover:text-brand hover:underline underline-offset-2 cursor-pointer align-middle"
                            title="Открыть источник для чтения"
                            onClick={() => setPreview(d)}>
                            {d.source}
                          </button>
                        </td>
                        <td><Badge>{LANG_LABEL[langOf(d)]}</Badge></td>
                        <td className="num text-right">{d.pages}</td>
                        <td className="num text-right">{d.chunks}</td>
                        <td><DocStatus d={d} /></td>
                        <td>
                          <button type="button"
                            className="btn btn-ghost btn-sm text-danger px-1.5"
                            title="Удалить источник из базы знаний"
                            onClick={() => deleteDoc(d)}>
                            <Icon name="trash" className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              )
            })}
            {tabDocs.length === 0 && (
              <tbody>
                <tr>
                  <td colSpan={7} className="text-center py-8 text-faint">
                    {docs.length === 0
                      ? 'Загрузите PDF-книги — они станут источником цитат для гипотез'
                      : 'Источников на этом языке пока нет — загрузите PDF или TXT.'}
                  </td>
                </tr>
              </tbody>
            )}
          </table>
        </div>
      </Panel>

      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
      {preview && <DocPreviewModal doc={preview} onClose={() => setPreview(null)} />}
      {uploadInfo && (
        <UploadInfoModal onClose={() => setUploadInfo(false)}
          onPick={() => { setUploadInfo(false); fileRef.current?.click() }} />
      )}
    </div>
  )
}
