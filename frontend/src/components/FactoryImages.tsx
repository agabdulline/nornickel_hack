import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { FactoryInfo } from '../types'
import { Badge, Icon, Modal, Panel } from './common'

/** Схемы фабрик из БД: смотреть, подписывать, добавлять свои, удалять.
 *  Сид — исходные изображения кейса, привязанные к КГМК/НОФ/ТОФ. */
export default function FactoryImages() {
  const [facts, setFacts] = useState<FactoryInfo[] | null>(null)
  const [err, setErr] = useState('')
  const [view, setView] = useState<{ url: string; title: string } | null>(null)
  const [busyFactory, setBusyFactory] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadTo = useRef<string>('')

  const load = () => api.factories().then(setFacts).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const rename = async (id: string, cur: string) => {
    const caption = window.prompt('Подпись изображения:', cur)
    if (caption === null) return
    try { await api.factoryImagePatch(id, caption); load() }
    catch (e) { setErr(String(e)) }
  }

  const remove = async (id: string) => {
    if (!window.confirm('Отвязать изображение от фабрики?')) return
    try { await api.factoryImageDelete(id); load() }
    catch (e) { setErr(String(e)) }
  }

  const upload = async (list: FileList | null) => {
    const factory = uploadTo.current
    if (!list?.length || !factory) return
    setBusyFactory(factory)
    for (const f of Array.from(list)) {
      try { await api.factoryImageUpload(factory, f) }
      catch (e) { setErr(String(e)) }
    }
    setBusyFactory(null)
    if (inputRef.current) inputRef.current.value = ''
    load()
  }

  return (
    <Panel title="Схемы фабрик"
      subtitle="исходные изображения из кейса, привязанные к фабрикам; можно добавить свои"
      bodyClass="p-3 space-y-4">
      {err && <div className="text-xs text-danger">{err}</div>}
      <input ref={inputRef} type="file" multiple className="hidden" id="fi-upload"
        accept=".png,.jpg,.jpeg,.webp,.bmp,.pdf" onChange={e => upload(e.target.files)} />
      {(facts ?? []).map(f => (
        <div key={f.factory}>
          <div className="flex items-center gap-2 mb-2">
            <span className="font-semibold text-sm">{f.factory}</span>
            {f.digitized
              ? <Badge tone="ok">граф оцифрован</Badge>
              : <Badge tone="warn">только изображения</Badge>}
            <button className="btn btn-sm !px-2 ml-auto"
              disabled={busyFactory === f.factory}
              onClick={() => { uploadTo.current = f.factory; inputRef.current?.click() }}>
              <Icon name="upload" className="w-3.5 h-3.5" />
              {busyFactory === f.factory ? 'загружаю…' : 'добавить'}
            </button>
          </div>
          <div className="flex flex-wrap gap-3">
            {f.images.map(img => (
              <figure key={img.id} className="w-44">
                <img src={api.factoryImageUrl(img.id)} alt={img.filename} loading="lazy"
                  className="h-28 w-full object-contain rounded-md border border-line bg-white
                    cursor-pointer transition-colors hover:border-brand"
                  onClick={() => setView({ url: api.factoryImageUrl(img.id),
                                           title: `${f.factory} · ${img.filename}` })} />
                <figcaption className="mt-1 text-[11px] leading-tight">
                  <span className="block truncate font-medium" title={img.filename}>{img.filename}</span>
                  <span className="flex items-center gap-1" style={{ color: 'var(--c-faint)' }}>
                    <button className="truncate hover:text-brand text-left flex-1"
                      title="Изменить подпись" onClick={() => rename(img.id, img.caption)}>
                      {img.caption || 'без подписи'}
                    </button>
                    <button className="shrink-0 hover:text-danger" title="Отвязать"
                      onClick={() => remove(img.id)}>
                      <Icon name="x" className="w-3 h-3" />
                    </button>
                  </span>
                </figcaption>
              </figure>
            ))}
            {f.images.length === 0 && (
              <div className="text-xs" style={{ color: 'var(--c-faint)' }}>изображений нет</div>
            )}
          </div>
        </div>
      ))}
      {view && (
        <Modal wide title={view.title} onClose={() => setView(null)}>
          <img src={view.url} alt={view.title}
            className="max-w-full rounded-md border border-line bg-white" />
        </Modal>
      )}
    </Panel>
  )
}
