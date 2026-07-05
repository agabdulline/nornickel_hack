import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, Line, LineKind, LineMaterial, Material, MaterialUnit } from '../types'
import { Icon } from './common'

const STANDARD_UNITS = ['т', 'кг', 'г', 'мг', 'м³', 'л', 'мл', '%', 'ppm', 'моль', 'ммоль', 'г/т']
const CUSTOM_UNIT = '__custom__'
const BRAND_ACCENT = { accentColor: 'var(--c-brand)' }

/** Select со стандартными единицами + «своя единица…»: при выборе последней
 * (или когда текущее значение уже не входит в стандартный список) рядом
 * появляется обычное текстовое поле для произвольной единицы. */
function UnitField({ value, onChange }: { value: MaterialUnit; onChange: (v: string) => void }) {
  const isCustom = !STANDARD_UNITS.includes(value)
  return (
    <>
      <select className="select w-24 py-1"
        value={isCustom ? CUSTOM_UNIT : value}
        onChange={e => onChange(e.target.value === CUSTOM_UNIT ? '' : e.target.value)}>
        {STANDARD_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
        <option value={CUSTOM_UNIT}>своя единица…</option>
      </select>
      {isCustom && (
        <input className="input w-24 py-1"
          placeholder="напр.: усл.ед." value={value} onChange={e => onChange(e.target.value)} autoFocus />
      )}
    </>
  )
}

/** Псевдо-линия «без привязки к объекту» — не сущность в БД, только состояние
 * выбора в форме проекта. Пока она выбрана, ограничения по оборудованию/сырью
 * не показываются вообще (площадка ещё не определена, гипотезы теоретические). */
export const NO_OBJECT_ID = '__unassigned__'
export const NO_OBJECT_LINE: Line = {
  id: NO_OBJECT_ID,
  name: 'Без привязки к объекту (площадка ещё не определена)',
  kind: 'производственная линия',
  ownership: 'в штате компании',
}

function useOutsideClose(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, onClose])
  return ref
}

function KindBadge({ kind }: { kind: LineKind }) {
  const cls = kind === 'лаборатория' ? 'badge-warn' : kind === 'фабрика' ? 'badge-brand' : ''
  return <span className={`badge ${cls}`}>{kind}</span>
}

/** Бейдж показывается только для внешних партнёров — свои институты не маркируются. */
function OwnershipBadge({ ownership }: { ownership: Line['ownership'] }) {
  if (ownership !== 'внешний подрядчик/партнёр') return null
  return <span className="badge badge-brand">внешний партнёр</span>
}

/** Кнопка удаления строки/чипа. */
function RemoveBtn({ onClick, className = '' }: { onClick: (e: React.MouseEvent) => void; className?: string }) {
  return (
    <button type="button" onClick={onClick} title="Удалить"
      className={`shrink-0 opacity-60 hover:opacity-100 hover:text-danger transition-opacity ${className}`}>
      <Icon name="x" className="w-3.5 h-3.5" />
    </button>
  )
}

/** Комбобокс «Фабрика/линия»: поиск по каталогу линий. Создание новой линии
 * (allowCreate) вынесено в «Базу знаний» — на главной оно отключено. */
export function LineCombobox({ value, onSelect, placeholder, allowCreate = true }: {
  value: Line | null; onSelect: (line: Line) => void; placeholder?: string
  allowCreate?: boolean
}) {
  const [lines, setLines] = useState<Line[]>([])
  const [search, setSearch] = useState(value?.name ?? '')
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState<LineKind>('производственная линия')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.lines().then(setLines).catch(() => setLines([])) }, [])
  // синхронизируем текст поиска только при смене ВЫБРАННОЙ линии, а не при каждой
  // перерисовке — иначе набранный текст стирался бы во время фильтрации списка
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setSearch(value?.name ?? '') }, [value?.id])

  const ref = useOutsideClose(open, () => { setOpen(false); setShowCreate(false) })

  const allOptions = [NO_OBJECT_LINE, ...lines]
  const filtered = allOptions.filter(l => l.name.toLowerCase().includes(search.trim().toLowerCase()))

  const pick = (line: Line) => {
    onSelect(line)
    setSearch(line.name)
    setOpen(false)
    setShowCreate(false)
  }

  const createLine = async () => {
    if (!newName.trim()) return
    setBusy(true)
    try {
      const line = await api.createLine({ name: newName.trim(), kind: newKind })
      setLines(prev => [...prev, line])
      pick(line)
      setNewName(''); setNewKind('производственная линия')
    } finally { setBusy(false) }
  }

  return (
    <div className="relative" ref={ref}>
      <input
        className="input mt-1.5"
        placeholder={placeholder ?? 'напр.: НОФ · вкрапленные руды'}
        value={search}
        onFocus={() => setOpen(true)}
        onChange={e => { setSearch(e.target.value); setOpen(true) }}
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full bg-surface border border-line rounded-lg
            shadow-pop max-h-72 overflow-auto text-sm">
          {filtered.map(l => (
            <button key={l.id} type="button" title={l.name}
              className="w-full text-left px-3 py-2 hover:bg-brand-tint transition-colors"
              onClick={() => pick(l)}>
              <div className={'leading-snug line-clamp-2 ' + (l.id === NO_OBJECT_ID ? 'text-faint italic' : '')}>
                {l.name}
              </div>
              {l.id !== NO_OBJECT_ID && (
                <div className="flex flex-wrap items-center gap-1 mt-1">
                  <KindBadge kind={l.kind} />
                  <OwnershipBadge ownership={l.ownership} />
                </div>
              )}
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="px-3 py-2 text-faint">Ничего не найдено</div>
          )}
          {allowCreate ? (
            <div className="border-t border-line">
              {!showCreate ? (
                <button type="button"
                  className="w-full text-left px-3 py-2 text-brand hover:bg-brand-tint font-semibold flex items-center gap-1.5 transition-colors"
                  onClick={() => setShowCreate(true)}>
                  <Icon name="plus" className="w-3.5 h-3.5" /> добавить новую фабрику/лабораторию
                </button>
              ) : (
                <div className="p-2.5 space-y-2">
                  <input className="input"
                    placeholder="напр.: НОФ · медистые руды"
                    value={newName} onChange={e => setNewName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createLine() } }} />
                  <div className="flex gap-3 text-sm">
                    <label className="flex items-center gap-1.5">
                      <input type="radio" style={BRAND_ACCENT} checked={newKind === 'производственная линия'}
                        onChange={() => setNewKind('производственная линия')} /> Производственная линия
                    </label>
                    <label className="flex items-center gap-1.5">
                      <input type="radio" style={BRAND_ACCENT} checked={newKind === 'лаборатория'}
                        onChange={() => setNewKind('лаборатория')} /> Лаборатория / НИОКР
                    </label>
                  </div>
                  <div className="flex gap-1.5">
                    <button type="button" className="btn btn-primary btn-sm" disabled={busy || !newName.trim()}
                      onClick={createLine}>Создать</button>
                    <button type="button" className="btn btn-sm" onClick={() => setShowCreate(false)}>Отмена</button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="border-t border-line px-3 py-2 text-xs text-faint">
              Новые фабрики и линии добавляются в «Базе знаний».
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const emptyEqForm = { name: '', position: '', category: '' }

/** Оборудование линии: чипы с ×/click-to-edit, write-through в мастер-данные линии.
 * Используется в блоке «Ограничения» формы проекта (п.7 ТЗ) — один элемент
 * редактируется за раз через общую форму добавления. */
export function EquipmentEditor({ lineId, value, onChange }: {
  lineId: string; value: Equipment[]; onChange: (v: Equipment[]) => void
}) {
  const [form, setForm] = useState(emptyEqForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const startEdit = (eq: Equipment) => {
    setEditingId(eq.id)
    setForm({ name: eq.name, position: eq.position, category: eq.category })
  }
  const cancelEdit = () => { setEditingId(null); setForm(emptyEqForm) }

  const submit = async () => {
    if (!form.name.trim()) return
    setBusy(true)
    try {
      if (editingId) {
        const updated = await api.updateEquipment(editingId, form)
        onChange(value.map(e => e.id === editingId ? updated : e))
      } else {
        const created = await api.addEquipment({ line_id: lineId, ...form })
        onChange([...value, created])
      }
      cancelEdit()
    } finally { setBusy(false) }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await api.deleteEquipment(id)
      onChange(value.filter(e => e.id !== id))
      if (editingId === id) cancelEdit()
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="field-label mb-1">Оборудование объекта</div>
      {value.length === 0 && (
        <div className="text-sm text-faint mb-1">
          Оборудование не указано — добавьте его ниже, чтобы гипотезы проверялись на соответствие.
        </div>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {value.map(e => (
            <span key={e.id}
              className={`badge cursor-pointer ${editingId === e.id ? 'badge-solid' : ''}`}
              onClick={() => startEdit(e)} title="Клик — редактировать">
              {e.name}{e.position && ` (${e.position})`}
              <RemoveBtn className="ml-0.5" onClick={ev => { ev.stopPropagation(); remove(e.id) }} />
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <input className="input flex-1 py-1"
          placeholder="напр.: Гидроциклон ГЦ-660"
          value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
        <input className="input w-24 py-1"
          placeholder="напр.: 5-3" value={form.position} onChange={e => setForm({ ...form, position: e.target.value })} />
        <input className="input w-32 py-1"
          placeholder="напр.: гидроциклон" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} />
        <button type="button" className="btn btn-sm" disabled={busy || !form.name.trim()} onClick={submit}>
          {editingId ? 'Сохранить' : '+ Добавить'}
        </button>
        {editingId && <button type="button" className="btn btn-sm" onClick={cancelEdit}>Отмена</button>}
      </div>
    </div>
  )
}

/** Поиск/выбор материала из общего справочника с возможностью ввести новое имя
 * (сервер сам заведёт запись через find-or-create при сохранении). */
function MaterialNameField({ value, onChange, catalog }: {
  value: string; onChange: (v: string) => void; catalog: Material[]
}) {
  const [open, setOpen] = useState(false)
  const ref = useOutsideClose(open, () => setOpen(false))
  const suggestions = catalog.filter(m =>
    value.trim() && m.name.toLowerCase().includes(value.trim().toLowerCase()))

  return (
    <div className="relative flex-1" ref={ref}>
      <input className="input py-1"
        placeholder="напр.: вкрапленная руда"
        value={value}
        onFocus={() => setOpen(true)}
        onChange={e => { onChange(e.target.value); setOpen(true) }} />
      {open && suggestions.length > 0 && (
        <div className="absolute z-20 mt-1 w-full bg-surface border border-line rounded-lg
            shadow-pop max-h-48 overflow-auto text-sm">
          {suggestions.map(s => (
            <button key={s.id} type="button" className="w-full text-left px-3 py-1.5 hover:bg-brand-tint transition-colors"
              onClick={() => { onChange(s.name); setOpen(false) }}>
              {s.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const emptyMatForm = { name: '', quantity: '', unit: 'т' as MaterialUnit }

/** Сырьё линии: чипы «название — кол-во ед.» с ×/click-to-edit, write-through.
 * Используется в блоке «Ограничения» формы проекта (п.7 ТЗ). */
export function MaterialsEditor({ lineId, value, onChange }: {
  lineId: string; value: LineMaterial[]; onChange: (v: LineMaterial[]) => void
}) {
  const [catalog, setCatalog] = useState<Material[]>([])
  const [form, setForm] = useState(emptyMatForm)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.materials().then(setCatalog).catch(() => setCatalog([])) }, [])

  const startEdit = (lm: LineMaterial) => {
    setEditingId(lm.id)
    setForm({ name: lm.name, quantity: String(lm.quantity), unit: lm.unit })
  }
  const cancelEdit = () => { setEditingId(null); setForm(emptyMatForm) }

  const submit = async () => {
    const name = form.name.trim()
    const qty = Number(form.quantity)
    if (!name || Number.isNaN(qty)) return
    setBusy(true)
    try {
      if (editingId) {
        const updated = await api.updateLineMaterial(editingId, { name, quantity: qty, unit: form.unit })
        onChange(value.map(m => m.id === editingId ? updated : m))
      } else {
        const created = await api.addLineMaterial({ line_id: lineId, name, quantity: qty, unit: form.unit })
        onChange([...value, created])
        if (!catalog.some(m => m.name.toLowerCase() === name.toLowerCase())) {
          setCatalog(prev => [...prev, { id: created.material_id, name: created.name }])
        }
      }
      cancelEdit()
    } finally { setBusy(false) }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await api.deleteLineMaterial(id)
      onChange(value.filter(m => m.id !== id))
      if (editingId === id) cancelEdit()
    } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="field-label mb-1">Сырьё</div>
      {value.length === 0 && (
        <div className="text-sm text-faint mb-1">Сырьё для этого объекта ещё не заведено.</div>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {value.map(m => (
            <span key={m.id}
              className={`badge cursor-pointer ${editingId === m.id ? 'badge-solid' : 'badge-brand'}`}
              onClick={() => startEdit(m)} title="Клик — редактировать">
              <span className="num">{m.name} — {m.quantity.toLocaleString('ru-RU')} {m.unit}</span>
              <RemoveBtn className="ml-0.5" onClick={ev => { ev.stopPropagation(); remove(m.id) }} />
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <MaterialNameField value={form.name} onChange={v => setForm({ ...form, name: v })} catalog={catalog} />
        <input type="number" min={0} className="input w-24 py-1 num"
          placeholder="напр.: 1200" value={form.quantity}
          onChange={e => setForm({ ...form, quantity: e.target.value })} />
        <UnitField value={form.unit} onChange={unit => setForm({ ...form, unit })} />
        <button type="button" className="btn btn-sm" disabled={busy || !form.name.trim() || form.quantity === ''}
          onClick={submit}>
          {editingId ? 'Сохранить' : '+ Добавить'}
        </button>
        {editingId && <button type="button" className="btn btn-sm" onClick={cancelEdit}>Отмена</button>}
      </div>
    </div>
  )
}

// ---------- п.8: единый режим редактирования карточки в «Базе знаний» ----------
// Столбец редактируемых строк вместо чипов: все позиции правятся одновременно,
// изменения копятся локально (staged) и уходят на бэкенд одним пакетом по
// клику «Сохранить» в LineCard — так что «Отмена» действительно ничего не трогает.

export interface DraftEquipment { id: string; name: string; position: string; category: string; isNew: boolean }
export interface DraftMaterial { id: string; name: string; quantity: string; unit: MaterialUnit; isNew: boolean }

export const toDraftEquipment = (list: Equipment[]): DraftEquipment[] =>
  list.map(e => ({ id: e.id, name: e.name, position: e.position, category: e.category, isNew: false }))

export const toDraftMaterial = (list: LineMaterial[]): DraftMaterial[] =>
  list.map(m => ({ id: m.id, name: m.name, quantity: String(m.quantity), unit: m.unit, isNew: false }))

export function EquipmentRows({ rows, onChange }: {
  rows: DraftEquipment[]; onChange: (rows: DraftEquipment[]) => void
}) {
  const counter = useRef(0)
  const [addForm, setAddForm] = useState(emptyEqForm)

  const updateRow = (id: string, patch: Partial<DraftEquipment>) =>
    onChange(rows.map(r => r.id === id ? { ...r, ...patch } : r))
  const removeRow = (id: string) => onChange(rows.filter(r => r.id !== id))
  const addRow = () => {
    if (!addForm.name.trim()) return
    onChange([...rows, { id: `new-${++counter.current}`, ...addForm, isNew: true }])
    setAddForm(emptyEqForm)
  }

  return (
    <div>
      <div className="field-label mb-1">Оборудование объекта</div>
      {rows.length === 0 && (
        <div className="text-sm text-faint mb-1">
          Оборудование не указано — добавьте его ниже, чтобы гипотезы проверялись на соответствие.
        </div>
      )}
      <div className="space-y-1.5">
        {rows.map(r => (
          <div key={r.id} className="flex gap-1.5 items-center">
            <input className="input flex-1 py-1"
              placeholder="напр.: Гидроциклон ГЦ-660"
              value={r.name} onChange={e => updateRow(r.id, { name: e.target.value })} />
            <input className="input w-24 py-1"
              placeholder="напр.: 5-3"
              value={r.position} onChange={e => updateRow(r.id, { position: e.target.value })} />
            <input className="input w-32 py-1"
              placeholder="напр.: гидроциклон"
              value={r.category} onChange={e => updateRow(r.id, { category: e.target.value })} />
            <RemoveBtn className="px-1" onClick={() => removeRow(r.id)} />
          </div>
        ))}
      </div>
      <div className="flex gap-1.5 mt-1.5 items-center">
        <input className="input flex-1 py-1"
          placeholder="напр.: Гидроциклон ГЦ-660"
          value={addForm.name} onChange={e => setAddForm({ ...addForm, name: e.target.value })} />
        <input className="input w-24 py-1"
          placeholder="напр.: 5-3"
          value={addForm.position} onChange={e => setAddForm({ ...addForm, position: e.target.value })} />
        <input className="input w-32 py-1"
          placeholder="напр.: гидроциклон"
          value={addForm.category} onChange={e => setAddForm({ ...addForm, category: e.target.value })} />
        <button type="button" className="btn btn-sm" disabled={!addForm.name.trim()} onClick={addRow}>+ Добавить</button>
      </div>
    </div>
  )
}

export function MaterialRows({ rows, onChange, catalog }: {
  rows: DraftMaterial[]; onChange: (rows: DraftMaterial[]) => void; catalog: Material[]
}) {
  const counter = useRef(0)
  const [addForm, setAddForm] = useState(emptyMatForm)

  const updateRow = (id: string, patch: Partial<DraftMaterial>) =>
    onChange(rows.map(r => r.id === id ? { ...r, ...patch } : r))
  const removeRow = (id: string) => onChange(rows.filter(r => r.id !== id))
  const addRow = () => {
    if (!addForm.name.trim() || addForm.quantity === '') return
    onChange([...rows, { id: `new-${++counter.current}`, ...addForm, isNew: true }])
    setAddForm(emptyMatForm)
  }

  return (
    <div>
      <div className="field-label mb-1">Сырьё</div>
      {rows.length === 0 && (
        <div className="text-sm text-faint mb-1">Сырьё для этого объекта ещё не заведено.</div>
      )}
      <div className="space-y-1.5">
        {rows.map(r => (
          <div key={r.id} className="flex gap-1.5 items-center">
            <MaterialNameField value={r.name} onChange={v => updateRow(r.id, { name: v })} catalog={catalog} />
            <input type="number" min={0} className="input w-24 py-1 num"
              placeholder="напр.: 1200"
              value={r.quantity} onChange={e => updateRow(r.id, { quantity: e.target.value })} />
            <UnitField value={r.unit} onChange={unit => updateRow(r.id, { unit })} />
            <RemoveBtn className="px-1" onClick={() => removeRow(r.id)} />
          </div>
        ))}
      </div>
      <div className="flex gap-1.5 mt-1.5 items-center">
        <MaterialNameField value={addForm.name} onChange={v => setAddForm({ ...addForm, name: v })} catalog={catalog} />
        <input type="number" min={0} className="input w-24 py-1 num"
          placeholder="напр.: 1200"
          value={addForm.quantity} onChange={e => setAddForm({ ...addForm, quantity: e.target.value })} />
        <UnitField value={addForm.unit} onChange={unit => setAddForm({ ...addForm, unit })} />
        <button type="button" className="btn btn-sm" disabled={!addForm.name.trim() || addForm.quantity === ''}
          onClick={addRow}>+ Добавить</button>
      </div>
    </div>
  )
}

/** Диффит staged-состояние против исходных списков и одним пакетом пишет
 * изменения в мастер-данные линии (write-through, п.7/8 ТЗ), затем
 * возвращает свежие списки с бэкенда. */
export async function commitLineEdits(lineId: string,
  original: { equipment: Equipment[]; materials: LineMaterial[] },
  draft: { equipment: DraftEquipment[]; materials: DraftMaterial[] },
): Promise<{ equipment: Equipment[]; materials: LineMaterial[] }> {
  const draftEqIds = new Set(draft.equipment.filter(r => !r.isNew).map(r => r.id))
  for (const e of original.equipment) {
    if (!draftEqIds.has(e.id)) await api.deleteEquipment(e.id)
  }
  for (const r of draft.equipment) {
    if (!r.name.trim()) continue
    if (r.isNew) {
      await api.addEquipment({ line_id: lineId, name: r.name.trim(), position: r.position.trim(), category: r.category.trim() })
    } else {
      const orig = original.equipment.find(e => e.id === r.id)
      if (orig && (orig.name !== r.name || orig.position !== r.position || orig.category !== r.category)) {
        await api.updateEquipment(r.id, { name: r.name, position: r.position, category: r.category })
      }
    }
  }

  const draftMatIds = new Set(draft.materials.filter(r => !r.isNew).map(r => r.id))
  for (const m of original.materials) {
    if (!draftMatIds.has(m.id)) await api.deleteLineMaterial(m.id)
  }
  for (const r of draft.materials) {
    const qty = Number(r.quantity)
    if (!r.name.trim() || Number.isNaN(qty)) continue
    if (r.isNew) {
      await api.addLineMaterial({ line_id: lineId, name: r.name.trim(), quantity: qty, unit: r.unit })
    } else {
      const orig = original.materials.find(m => m.id === r.id)
      if (orig && (orig.name !== r.name || orig.quantity !== qty || orig.unit !== r.unit)) {
        await api.updateLineMaterial(r.id, { name: r.name, quantity: qty, unit: r.unit })
      }
    }
  }

  const [equipment, materials] = await Promise.all([
    api.equipmentForLine(lineId), api.lineMaterials(lineId),
  ])
  return { equipment, materials }
}
