import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { ProjectFile } from '../types'
import { Icon, Panel, SectionLabel } from './common'

const KIND_LABEL: Record<string, string> = {
  scheme: 'схема', image: 'картинка', pdf: 'PDF', text: 'текст', other: 'файл',
}

function statusLabel(f: ProjectFile): { text: string; tone: 'ok' | 'warn' | 'muted' } {
  if (f.status === 'ocr') return { text: `распознано OCR · ${f.chars} симв.`, tone: 'ok' }
  if (f.status === 'text') return { text: `текст извлечён · ${f.chars} симв.`, tone: 'ok' }
  if (f.status === 'no_ocr') return { text: 'OCR недоступен — текст не извлечён', tone: 'warn' }
  if (f.status === 'scan_no_text') return { text: 'скан без текстового слоя', tone: 'warn' }
  if (f.status.startsWith('error')) return { text: 'не удалось извлечь текст', tone: 'warn' }
  return { text: f.status, tone: 'muted' }
}

/** Материалы проекта: регламенты, схемы, фото, заметки. Картинки распознаёт
 *  Yandex OCR; извлечённый текст учитывается при генерации гипотез; картинки-
 *  схемы показываются на экране диагностики рядом со схемой фабрики. */
export default function ProjectFiles({ pid, compact = false }: { pid: string; compact?: boolean }) {
  const [files, setFiles] = useState<ProjectFile[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true
    api.projectFiles(pid).then(fs => { if (live) setFiles(fs) }).catch(() => { if (live) setFiles([]) })
    return () => { live = false }
  }, [pid])

  const upload = async (list: FileList | null) => {
    if (!list?.length) return
    setBusy(true); setErr('')
    for (const f of Array.from(list)) {
      try {
        const rec = await api.projectFileUpload(pid, f)
        setFiles(cur => [...(cur ?? []), rec])
      } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
    }
    setBusy(false)
    if (inputRef.current) inputRef.current.value = ''
  }

  const remove = async (fid: string) => {
    if (!window.confirm('Удалить материал?')) return
    try {
      await api.projectFileDelete(pid, fid)
      setFiles(cur => (cur ?? []).filter(x => x.id !== fid))
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }

  const body = (
    <div className="space-y-2">
      {(files ?? []).map(f => {
        const st = statusLabel(f)
        return (
          <div key={f.id} className="card-2 px-3 py-2 flex items-center gap-2.5 text-sm">
            <Icon name={f.kind === 'scheme' || f.kind === 'image' ? 'map' : 'doc'}
              className="w-4 h-4 shrink-0 text-faint" />
            <div className="flex-1 min-w-0">
              <a className="font-medium truncate block hover:text-brand"
                href={api.projectFileUrl(pid, f.id)} target="_blank" rel="noreferrer"
                title={f.preview || f.filename}>
                {f.filename}
              </a>
              <div className="text-[11px]"
                style={{ color: st.tone === 'ok' ? 'var(--c-ok)' : st.tone === 'warn' ? 'var(--c-warn)' : 'var(--c-faint)' }}>
                {KIND_LABEL[f.kind] ?? f.kind}{f.kind === 'scheme' ? ' · покажем на диагностике' : ''} · {st.text}
              </div>
            </div>
            <button className="btn btn-ghost !px-2 shrink-0" title="Удалить"
              onClick={() => remove(f.id)}>
              <Icon name="trash" className="w-4 h-4" />
            </button>
          </div>
        )
      })}
      {files !== null && files.length === 0 && (
        <div className="text-xs" style={{ color: 'var(--c-faint)' }}>
          Регламенты, схемы, фотографии, заметки — картинки распознаёт Яндекс OCR,
          извлечённый текст учитывается при генерации гипотез.
        </div>
      )}
      {err && <div className="text-xs text-danger">{err}</div>}
      <div>
        <input ref={inputRef} type="file" multiple className="hidden" id={`pf-${pid}`}
          accept=".png,.jpg,.jpeg,.webp,.bmp,.pdf,.txt,.md,.csv,.docx"
          onChange={e => upload(e.target.files)} />
        <label htmlFor={`pf-${pid}`}
          className={`btn btn-sm cursor-pointer ${busy ? 'opacity-60 pointer-events-none' : ''}`}>
          <Icon name="upload" className="w-4 h-4" />
          {busy ? 'Загружаю и распознаю…' : 'Добавить материалы'}
        </label>
      </div>
    </div>
  )

  if (compact) {
    return (
      <div>
        <SectionLabel>Материалы проекта</SectionLabel>
        {body}
      </div>
    )
  }
  return (
    <Panel title="Материалы проекта"
      subtitle="регламенты, схемы, фото — текст извлекается и учитывается при генерации"
      bodyClass="p-3">
      {body}
    </Panel>
  )
}
