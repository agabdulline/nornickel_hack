import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { FactoryInfo, FlowsheetData } from '../types'
import { Badge, Icon, Modal, Panel } from './common'
import { FlowsheetTextView } from './FlowsheetText'

/** Попап перед добавлением изображения схемы (для оргов/жюри). */
function AddImageInfoModal({ factory, digitized, onPick, onClose }: {
  factory: string; digitized: boolean; onPick: () => void; onClose: () => void
}) {
  return (
    <Modal title={`Добавление схемы: ${factory}`} onClose={onClose}>
      <div className="space-y-3 text-sm leading-relaxed">
        <p>
          Изображение прикладывается к фабрике как исходный материал —
          сохраняется <b>мгновенно</b> и открывается по клику из этой галереи.
        </p>
        {digitized ? (
          <p>
            Граф этой фабрики <b>уже оцифрован из материалов кейса</b>: каждая
            цифра (времена, % твёрдого, расходы реагентов, металлобаланс)
            перепроверена вторым независимым проходом по изображениям.
            Новые картинки его <b>не изменяют</b> — выверенная схема
            неприкосновенна и именно она используется в диагнозах и генерации.
          </p>
        ) : (
          <p>
            Граф этой фабрики не оцифрован. Автоматическая оцифровка
            изображения доступна в карточке линии («Фабрики и лаборатории» →
            линия → «загрузить схему»): OCR подписей (~5–10 сек) + сборка
            структуры моделью (~1–2 мин, в фоне) — результат помечается как
            черновик и учитывается в диагнозах и генерации.
          </p>
        )}
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

/** Модалка «как оцифрован граф»: текстовое представление флоушита фабрики. */
function DigitizedView({ factory, onClose }: { factory: string; onClose: () => void }) {
  const [fs, setFs] = useState<FlowsheetData | null>(null)
  const [source, setSource] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => {
    api.factoryFlowsheet(factory)
      .then(r => { setFs(r.flowsheet); setSource(r.source ?? 'case') })
      .catch(e => setErr(String(e)))
  }, [factory])
  return (
    <Modal wide onClose={onClose}
      title={<span className="inline-flex items-center gap-2">
        Как оцифрован граф: {factory}
        {source === 'case' && fs && <Badge tone="ok">выверено вручную из кейса</Badge>}
        {source === 'upload' && fs && <Badge tone="warn">черновик из загрузки</Badge>}
      </span>}>
      {err && <div className="text-sm text-faint">Граф не оцифрован: {err}</div>}
      {fs ? <FlowsheetTextView fs={fs} /> : !err &&
        <div className="text-sm text-faint">Загружаю…</div>}
    </Modal>
  )
}

/** Схемы фабрик из БД: папки-секции (свёрнуты), просмотр/подписи/добавление
 * с поясняющим попапом, кнопка «как оцифрован граф». */
export default function FactoryImages() {
  const [facts, setFacts] = useState<FactoryInfo[] | null>(null)
  const [err, setErr] = useState('')
  const [view, setView] = useState<{ url: string; title: string } | null>(null)
  const [digView, setDigView] = useState<string | null>(null)
  const [addInfo, setAddInfo] = useState<FactoryInfo | null>(null)
  const [openFacts, setOpenFacts] = useState<Set<string>>(new Set())
  const [busyFactory, setBusyFactory] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadTo = useRef<string>('')

  const load = () => api.factories().then(setFacts).catch(e => setErr(String(e)))
  useEffect(() => { load() }, [])

  const toggleOpen = (f: string) =>
    setOpenFacts(prev => {
      const next = new Set(prev)
      if (next.has(f)) next.delete(f)
      else next.add(f)
      return next
    })

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
    setOpenFacts(prev => new Set(prev).add(factory))
    load()
  }

  return (
    <Panel title="Схемы фабрик"
      subtitle="исходные изображения из кейса, привязанные к фабрикам; можно добавить свои"
      bodyClass="p-3 space-y-2">
      {err && <div className="text-xs text-danger">{err}</div>}
      <input ref={inputRef} type="file" multiple className="hidden" id="fi-upload"
        accept=".png,.jpg,.jpeg,.webp,.bmp,.pdf" onChange={e => upload(e.target.files)} />
      {(facts ?? []).map(f => {
        const opened = openFacts.has(f.factory)
        return (
          <div key={f.factory} className="py-1">
            <div className="flex items-center gap-2">
              <button type="button" aria-expanded={opened}
                className="group inline-flex items-center gap-1.5 cursor-pointer"
                title={opened ? 'Свернуть' : `Показать изображения (${f.images.length})`}
                onClick={() => toggleOpen(f.factory)}>
                <Icon name="arrowRight" strokeWidth={2.5}
                  className={`w-4 h-4 text-faint transition-transform duration-200 ${opened ? 'rotate-90' : ''}`} />
                <span className="font-semibold text-sm group-hover:text-brand">{f.factory}</span>
                <span className="num text-xs text-faint">({f.images.length})</span>
              </button>
              {f.digitized
                ? <Badge tone="ok">граф оцифрован</Badge>
                : <Badge tone="warn">только изображения</Badge>}
              {f.digitized && (
                <button className="text-xs text-brand hover:underline underline-offset-2 cursor-pointer"
                  title="Посмотреть, во что оцифрована схема — переделы, узлы, режимы"
                  onClick={() => setDigView(f.factory)}>
                  как оцифрован
                </button>
              )}
              <button className="btn btn-sm !px-2 ml-auto"
                disabled={busyFactory === f.factory}
                onClick={() => setAddInfo(f)}>
                <Icon name="upload" className="w-3.5 h-3.5" />
                {busyFactory === f.factory ? 'загружаю…' : 'добавить'}
              </button>
            </div>
            {opened && (
              <div className="flex flex-wrap gap-3 mt-2 ml-6 animate-in">
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
            )}
          </div>
        )
      })}
      {view && (
        <Modal wide title={view.title} onClose={() => setView(null)}>
          <img src={view.url} alt={view.title}
            className="max-w-full rounded-md border border-line bg-white" />
        </Modal>
      )}
      {digView && <DigitizedView factory={digView} onClose={() => setDigView(null)} />}
      {addInfo && (
        <AddImageInfoModal factory={addInfo.factory} digitized={addInfo.digitized}
          onClose={() => setAddInfo(null)}
          onPick={() => {
            uploadTo.current = addInfo.factory
            setAddInfo(null)
            inputRef.current?.click()
          }} />
      )}
    </Panel>
  )
}
