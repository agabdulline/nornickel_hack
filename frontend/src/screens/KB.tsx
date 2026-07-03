import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { KbDoc } from '../types'
import { Badge, ChunkModal, ErrorBox, Icon, Panel, SectionLabel } from '../components/common'

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
      {chunk && <ChunkModal chunkId={chunk} onClose={() => setChunk(null)} />}
    </div>
  )
}
