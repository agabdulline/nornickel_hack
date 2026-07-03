import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { KbDoc } from '../types'
import { ChunkModal, ErrorBox } from '../components/common'

function DocStatus({ d }: { d: KbDoc }) {
  if (d.status === 'indexed')
    return <span className="badge bg-green-100 text-green-800">✓ индексирован</span>
  if (d.status === 'indexed_ocr')
    return <span className="badge bg-green-100 text-green-800"
      title="Скан распознан Yandex Vision OCR и проиндексирован">✓ распознан (OCR)</span>
  if (d.status === 'ocr_processing') {
    const pct = d.pages ? Math.round(((d.ocr_done ?? 0) / d.pages) * 100) : 0
    return (
      <span className="badge bg-teal-50 text-teal-800 border border-teal-200">
        <span className="inline-block w-3 h-3 mr-1.5 rounded-full border-2 border-teal-600
          border-t-transparent animate-spin" />
        распознаём… <span className="num ml-1">{d.ocr_done ?? 0}/{d.pages} ({pct}%)</span>
      </span>
    )
  }
  if (d.status === 'ocr_failed')
    return <span className="badge bg-red-100 text-red-800" title={d.error}>✗ OCR не удался</span>
  return <span className="badge bg-amber-100 text-amber-800"
    title="Скан без текстового слоя — в поиске не участвует">⚠ требуется OCR</span>
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
                  <td><DocStatus d={d} /></td>
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
      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
    </div>
  )
}
