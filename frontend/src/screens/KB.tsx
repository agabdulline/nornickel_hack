import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, KbDoc, Line, LineKind, LineMaterial, Material, LineOwnership } from '../types'
import { Badge, ChunkModal, ErrorBox, Icon, Panel, SectionLabel } from '../components/common'
import {
  commitLineEdits, type DraftEquipment, type DraftMaterial, EquipmentRows, MaterialRows,
  toDraftEquipment, toDraftMaterial,
} from '../components/lines'

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
    const [eq, mats] = await Promise.all([api.equipmentForLine(line.id), api.lineMaterials(line.id)])
    setEquipment(eq); setMaterials(mats)
    return { eq, mats }
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
        <div className="flex flex-wrap gap-1.5 items-center bg-surface-2 border border-line rounded-md p-2">
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
                  <button type="button" className="flex items-center gap-2 text-left flex-1"
                    onClick={() => toggleExpand(line)}>
                    <span className="font-medium text-base">{line.name}</span>
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
                    <>
                      <button type="button" className="text-xs text-brand hover:underline"
                        onClick={() => startEdit(line)}>Изменить</button>
                      <button type="button" className="text-faint text-sm w-5"
                        onClick={() => toggleExpand(line)}>{isExpanded ? '▲' : '▼'}</button>
                    </>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="mt-2 pl-2 border-l-2 border-line space-y-3">
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

  const ask = async () => {
    if (!question.trim()) return
    setAsking(true); setAnswer(null)
    try { setAnswer(await api.kbAsk(question)) }
    catch (e) { setErr(String(e)) } finally { setAsking(false) }
  }

  return (
    <div className="space-y-4">
      <LinesSection />
      <div className="grid md:grid-cols-2 gap-4 items-start">
      <div className="space-y-3">
        {err && <ErrorBox error={err} />}

        <Panel
          title="Документы"
          subtitle="PDF-книги — источник цитат для гипотез"
          bodyClass="p-0"
          actions={
            <>
              <button className="btn btn-primary btn-sm" disabled={uploading}
                onClick={() => fileRef.current?.click()}>
                <Icon name="upload" className="w-4 h-4" />
                {uploading ? 'Индексирую…' : 'Загрузить PDF'}
              </button>
              <input ref={fileRef} type="file" accept=".pdf" className="hidden"
                onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
            </>
          }
        >
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Источник</th>
                  <th className="text-right">Стр.</th>
                  <th className="text-right">Чанков</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody className="stagger">
                {docs.map(d => (
                  <tr key={d.doc_id}>
                    <td className="max-w-xs truncate" title={d.source}>{d.source}</td>
                    <td className="num text-right">{d.pages}</td>
                    <td className="num text-right">{d.chunks}</td>
                    <td><DocStatus d={d} /></td>
                  </tr>
                ))}
                {docs.length === 0 &&
                  <tr>
                    <td colSpan={4} className="text-center py-8 text-faint">
                      Загрузите PDF-книги — они станут источником цитат для гипотез
                    </td>
                  </tr>}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="space-y-3">
        <Panel title="Вопрос к базе знаний" subtitle="Ответ строится только по проиндексированным документам, с цитатами и страницами">
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
                <div className="space-y-1.5 stagger">
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
      </div>
      </div>
      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
    </div>
  )
}
