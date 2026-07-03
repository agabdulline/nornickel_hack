import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, KbDoc, Line, LineMaterial } from '../types'
import { ChunkModal, ErrorBox } from '../components/common'
import { EquipmentEditor, MaterialsEditor } from '../components/lines'

/** Раздел «Фабрики и лаборатории»: те же мастер-данные, что и в форме проекта
 * (write-through) — два входа в одни и те же записи, а не два разных набора. */
function LinesSection() {
  const [lines, setLines] = useState<Line[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [equipment, setEquipment] = useState<Equipment[]>([])
  const [materials, setMaterials] = useState<LineMaterial[]>([])
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<'factory' | 'lab'>('factory')
  const [editingLineId, setEditingLineId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editType, setEditType] = useState<'factory' | 'lab'>('factory')

  useEffect(() => { api.lines().then(setLines) }, [])

  const toggleExpand = async (line: Line) => {
    if (expanded === line.id) { setExpanded(null); return }
    setExpanded(line.id)
    const [eq, mats] = await Promise.all([
      line.type === 'lab' ? Promise.resolve([]) : api.equipmentForLine(line.id),
      api.lineMaterials(line.id),
    ])
    setEquipment(eq); setMaterials(mats)
  }

  const createLine = async () => {
    if (!newName.trim()) return
    const line = await api.createLine({ name: newName.trim(), type: newType })
    setLines(prev => [...prev, line].sort((a, b) => a.name.localeCompare(b.name)))
    setNewName(''); setNewType('factory'); setCreating(false)
  }

  const startEditLine = (line: Line) => {
    setEditingLineId(line.id); setEditName(line.name); setEditType(line.type)
  }
  const saveEditLine = async () => {
    if (!editingLineId || !editName.trim()) return
    const updated = await api.updateLine(editingLineId, { name: editName.trim(), type: editType })
    setLines(prev => prev.map(l => l.id === updated.id ? updated : l))
    setEditingLineId(null)
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
            placeholder="название фабрики/линии или лаборатории"
            value={newName} onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createLine() } }} />
          <select className="border border-slate-300 rounded px-2 py-1 text-sm"
            value={newType} onChange={e => setNewType(e.target.value as 'factory' | 'lab')}>
            <option value="factory">Фабрика/линия</option>
            <option value="lab">Лаборатория/НИОКР</option>
          </select>
          <button className="btn btn-primary" disabled={!newName.trim()} onClick={createLine}>Создать</button>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {lines.map(line => (
          <div key={line.id} className="py-2">
            <div className="flex items-center justify-between">
              {editingLineId === line.id ? (
                <div className="flex flex-wrap gap-1.5 items-center">
                  <input className="border border-slate-300 rounded px-2 py-1 text-sm"
                    value={editName} onChange={e => setEditName(e.target.value)} />
                  <select className="border border-slate-300 rounded px-2 py-1 text-sm"
                    value={editType} onChange={e => setEditType(e.target.value as 'factory' | 'lab')}>
                    <option value="factory">фабрика</option>
                    <option value="lab">лаборатория</option>
                  </select>
                  <button className="btn" onClick={saveEditLine}>Сохранить</button>
                  <button className="btn" onClick={() => setEditingLineId(null)}>Отмена</button>
                </div>
              ) : (
                <button type="button" className="flex items-center gap-2 text-left flex-1"
                  onClick={() => toggleExpand(line)}>
                  <span className="font-medium">{line.name}</span>
                  <span className={`badge ${line.type === 'lab' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-700'}`}>
                    {line.type === 'lab' ? 'лаборатория' : 'фабрика'}
                  </span>
                </button>
              )}
              <div className="flex items-center gap-2">
                {editingLineId !== line.id && (
                  <button type="button" className="text-xs text-teal-700 hover:underline"
                    onClick={() => startEditLine(line)}>изменить</button>
                )}
                <button type="button" className="text-slate-400 text-sm w-5"
                  onClick={() => toggleExpand(line)}>{expanded === line.id ? '▲' : '▼'}</button>
              </div>
            </div>
            {expanded === line.id && (
              <div className="mt-2 pl-2 border-l-2 border-slate-100 space-y-3">
                {line.type !== 'lab' && (
                  <EquipmentEditor lineId={line.id} value={equipment} onChange={setEquipment} />
                )}
                <MaterialsEditor lineId={line.id} value={materials} onChange={setMaterials} />
              </div>
            )}
          </div>
        ))}
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
