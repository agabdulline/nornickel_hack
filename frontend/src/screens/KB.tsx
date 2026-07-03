import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, KbDoc, Line, LineKind, LineMaterial, Material, LineOwnership } from '../types'
import { ChunkModal, ErrorBox } from '../components/common'
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
    <div className="card p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-semibold">Фабрики и лаборатории</div>
        <button className="btn" onClick={() => setCreating(v => !v)}>+ Новая линия/лаборатория</button>
      </div>

      {creating && (
        <div className="flex flex-wrap gap-1.5 items-center bg-slate-50 border border-slate-200 rounded p-2">
          <input className="flex-1 min-w-40 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
            placeholder="напр.: НОФ · медистые руды"
            value={newName} onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createLine() } }} />
          <select className="border border-slate-300 rounded px-2 py-1 text-sm"
            value={newKind} onChange={e => setNewKind(e.target.value as LineKind)}>
            {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
          <button className="btn btn-primary" disabled={!newName.trim()} onClick={createLine}>Создать</button>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {lines.map(line => {
          const isEditing = editingLineId === line.id
          const isExpanded = expanded === line.id
          return (
            <div key={line.id} className="py-2">
              <div className="flex items-center justify-between gap-2">
                {isEditing ? (
                  <div className="flex flex-wrap gap-1.5 items-center flex-1">
                    <input className="flex-1 min-w-40 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
                      placeholder="напр.: НОФ · вкрапленные руды"
                      value={draftName} onChange={e => setDraftName(e.target.value)} />
                    <select className="border border-slate-300 rounded px-2 py-1 text-sm"
                      value={draftKind} onChange={e => setDraftKind(e.target.value as LineKind)}>
                      {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
                    </select>
                    <select className="border border-slate-300 rounded px-2 py-1 text-sm"
                      value={draftOwnership} onChange={e => setDraftOwnership(e.target.value as LineOwnership)}>
                      {OWNERSHIP_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                ) : (
                  <button type="button" className="flex items-center gap-2 text-left flex-1"
                    onClick={() => toggleExpand(line)}>
                    <span className="font-medium text-base">{line.name}</span>
                    {line.ownership === 'внешний подрядчик/партнёр' && (
                      <span className="badge bg-purple-50 text-purple-800">внешний партнёр</span>
                    )}
                    <span className={`badge ${line.kind === 'лаборатория' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-700'}`}>
                      {line.kind}
                    </span>
                  </button>
                )}
                <div className="flex items-center gap-2 shrink-0">
                  {isEditing ? (
                    <>
                      <button type="button" className="btn btn-primary" disabled={saving}
                        onClick={() => saveEdit(line)}>Сохранить</button>
                      <button type="button" className="btn" disabled={saving} onClick={cancelEdit}>Отмена</button>
                    </>
                  ) : (
                    <>
                      <button type="button" className="text-xs text-teal-700 hover:underline"
                        onClick={() => startEdit(line)}>Изменить</button>
                      <button type="button" className="text-slate-400 text-sm w-5"
                        onClick={() => toggleExpand(line)}>{isExpanded ? '▲' : '▼'}</button>
                    </>
                  )}
                </div>
              </div>

              {isExpanded && (
                <div className="mt-2 pl-2 border-l-2 border-slate-100 space-y-3">
                  {isEditing ? (
                    <>
                      <EquipmentRows rows={draftEquipment} onChange={setDraftEquipment} />
                      <MaterialRows rows={draftMaterials} onChange={setDraftMaterials} catalog={materialsCatalog} />
                    </>
                  ) : (
                    <>
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Оборудование объекта</div>
                        {equipment.length === 0 && (
                          <div className="text-sm text-slate-400">
                            Оборудование не указано — добавьте его через «Изменить».
                          </div>
                        )}
                        <div className="flex flex-wrap gap-1.5">
                          {equipment.map(e => (
                            <span key={e.id} className="badge bg-slate-100 text-slate-700">
                              {e.name}{e.position && ` (${e.position})`}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Сырьё</div>
                        {materials.length === 0 && (
                          <div className="text-sm text-slate-400">Сырьё для этого объекта ещё не заведено.</div>
                        )}
                        <div className="flex flex-wrap gap-1.5">
                          {materials.map(m => (
                            <span key={m.id} className="badge bg-teal-50 text-teal-800">
                              {m.name} — {m.quantity.toLocaleString('ru-RU')} {m.unit}
                            </span>
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
          <div className="text-slate-400 text-sm text-center py-4">Пока нет ни одной линии/лаборатории.</div>
        )}
      </div>
    </div>
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
        <div className="card p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="font-semibold">Документы</div>
            <button className="btn" disabled={uploading} onClick={() => fileRef.current?.click()}>
              {uploading ? 'Индексирую…' : '+ Загрузить PDF'}
            </button>
            <input ref={fileRef} type="file" accept=".pdf" className="hidden"
              onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
          </div>
          <table className="tbl">
            <thead><tr><th>Источник</th><th className="text-right">Стр.</th>
              <th className="text-right">Чанков</th><th>Статус</th></tr></thead>
            <tbody>
              {docs.map(d => (
                <tr key={d.doc_id}>
                  <td className="max-w-xs truncate" title={d.source}>{d.source}</td>
                  <td className="num text-right">{d.pages}</td>
                  <td className="num text-right">{d.chunks}</td>
                  <td>
                    {d.status === 'indexed'
                      ? <span className="badge bg-green-100 text-green-800">✓ индексирован</span>
                      : <span className="badge bg-amber-100 text-amber-800"
                          title="Скан без текстового слоя — в поиске не участвует">
                          ⚠ требуется OCR
                        </span>}
                  </td>
                </tr>
              ))}
              {docs.length === 0 &&
                <tr><td colSpan={4} className="text-slate-400 text-center py-4">
                  Загрузите PDF-книги — они станут источником цитат для гипотез
                </td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-3">
        <div className="card p-3 space-y-2">
          <div className="font-semibold">Вопрос к базе знаний</div>
          <div className="flex gap-2">
            <input className="flex-1 border border-slate-300 rounded px-2 py-1.5 text-sm"
              placeholder="напр.: как извлекают золото из упорных руд?"
              value={question} onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && ask()} />
            <button className="btn btn-primary" disabled={asking} onClick={ask}>
              {asking ? '…' : 'Спросить'}
            </button>
          </div>
          <div className="text-xs text-slate-400">
            Ответ строится только по проиндексированным документам, с цитатами и страницами.
          </div>
        </div>

        {answer && (
          <div className="card p-3 space-y-3">
            <div className="text-sm whitespace-pre-wrap leading-relaxed">{answer.answer}</div>
            {answer.citations.length > 0 && (
              <div className="space-y-1.5 border-t border-slate-100 pt-2">
                <div className="text-xs text-slate-500 font-medium">Источники</div>
                {answer.citations.map((c, i) => (
                  <button key={i} className="block text-left w-full text-xs bg-slate-50 border
                      border-slate-200 rounded p-2 hover:bg-teal-50 cursor-pointer"
                    onClick={() => setChunk(c.chunk_id)}>
                    «{c.quote.slice(0, 140)}…»
                    <span className="text-slate-500"> — {c.source}, с. {c.page}</span>
                  </button>
                ))}
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
