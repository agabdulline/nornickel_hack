import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Equipment, Line, LineMaterial, Material, MaterialUnit } from '../types'

const UNITS: MaterialUnit[] = ['т', 'кг', '%', 'м³']

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

/** Комбобокс «Фабрика/линия»: поиск по каталогу линий + инлайн-создание новой. */
export function LineCombobox({ value, onSelect, placeholder }: {
  value: Line | null; onSelect: (line: Line) => void; placeholder?: string
}) {
  const [lines, setLines] = useState<Line[]>([])
  const [search, setSearch] = useState(value?.name ?? '')
  const [open, setOpen] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<'factory' | 'lab'>('factory')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.lines().then(setLines).catch(() => setLines([])) }, [])
  // синхронизируем текст поиска только при смене ВЫБРАННОЙ линии, а не при каждой
  // перерисовке — иначе набранный текст стирался бы во время фильтрации списка
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setSearch(value?.name ?? '') }, [value?.id])

  const ref = useOutsideClose(open, () => { setOpen(false); setShowCreate(false) })

  const filtered = lines.filter(l => l.name.toLowerCase().includes(search.trim().toLowerCase()))

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
      const line = await api.createLine({ name: newName.trim(), type: newType })
      setLines(prev => [...prev, line])
      pick(line)
      setNewName(''); setNewType('factory')
    } finally { setBusy(false) }
  }

  return (
    <div className="relative" ref={ref}>
      <input
        className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 text-sm placeholder:text-slate-400"
        placeholder={placeholder ?? 'выберите фабрику/линию или лабораторию…'}
        value={search}
        onFocus={() => setOpen(true)}
        onChange={e => { setSearch(e.target.value); setOpen(true) }}
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full bg-white border border-slate-300 rounded shadow-lg
            max-h-72 overflow-auto text-sm">
          {filtered.map(l => (
            <button key={l.id} type="button"
              className="w-full text-left px-2 py-1.5 hover:bg-teal-50 flex items-center justify-between gap-2"
              onClick={() => pick(l)}>
              <span>{l.name}</span>
              <span className={`badge ${l.type === 'lab' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-700'}`}>
                {l.type === 'lab' ? 'лаборатория' : 'фабрика'}
              </span>
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="px-2 py-1.5 text-slate-400">Ничего не найдено</div>
          )}
          <div className="border-t border-slate-100">
            {!showCreate ? (
              <button type="button" className="w-full text-left px-2 py-1.5 text-teal-700 hover:bg-teal-50 font-medium"
                onClick={() => setShowCreate(true)}>
                + добавить новую фабрику/линию
              </button>
            ) : (
              <div className="p-2 space-y-1.5">
                <input className="w-full border border-slate-300 rounded px-2 py-1 placeholder:text-slate-400"
                  placeholder="название фабрики/линии или лаборатории"
                  value={newName} onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createLine() } }} />
                <div className="flex gap-3">
                  <label className="flex items-center gap-1">
                    <input type="radio" checked={newType === 'factory'}
                      onChange={() => setNewType('factory')} /> Фабрика/линия
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="radio" checked={newType === 'lab'}
                      onChange={() => setNewType('lab')} /> Лаборатория / НИОКР
                  </label>
                </div>
                <div className="flex gap-1.5">
                  <button type="button" className="btn btn-primary" disabled={busy || !newName.trim()}
                    onClick={createLine}>Создать</button>
                  <button type="button" className="btn" onClick={() => setShowCreate(false)}>Отмена</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const emptyEqForm = { name: '', position: '', category: '' }

/** Оборудование линии: чипы с ×/click-to-edit, write-through в мастер-данные линии. */
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
      <div className="text-xs text-slate-500 mb-1">Оборудование линии</div>
      {value.length === 0 && (
        <div className="text-sm text-slate-400 mb-1">На этой линии оборудование ещё не заведено.</div>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {value.map(e => (
            <span key={e.id}
              className={`badge cursor-pointer ${editingId === e.id ? 'bg-teal-100 text-teal-800' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
              onClick={() => startEdit(e)} title="Клик — редактировать">
              {e.name}{e.position && ` (${e.position})`}
              <button type="button" className="ml-1 text-slate-400 hover:text-red-600"
                onClick={ev => { ev.stopPropagation(); remove(e.id) }}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <input className="flex-1 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
          placeholder="добавить единицу оборудования…"
          value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
        <input className="w-24 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
          placeholder="позиция" value={form.position} onChange={e => setForm({ ...form, position: e.target.value })} />
        <input className="w-32 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
          placeholder="категория" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} />
        <button type="button" className="btn" disabled={busy || !form.name.trim()} onClick={submit}>
          {editingId ? 'Сохранить' : '+ Добавить'}
        </button>
        {editingId && <button type="button" className="btn" onClick={cancelEdit}>Отмена</button>}
      </div>
    </div>
  )
}

const emptyMatForm = { name: '', quantity: '', unit: 'т' as MaterialUnit }

/** Сырьё линии: чипы «название — кол-во ед.» с ×/click-to-edit, write-through. */
export function MaterialsEditor({ lineId, value, onChange }: {
  lineId: string; value: LineMaterial[]; onChange: (v: LineMaterial[]) => void
}) {
  const [catalog, setCatalog] = useState<Material[]>([])
  const [form, setForm] = useState(emptyMatForm)
  const [nameOpen, setNameOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.materials().then(setCatalog).catch(() => setCatalog([])) }, [])
  const nameRef = useOutsideClose(nameOpen, () => setNameOpen(false))

  const suggestions = catalog.filter(m =>
    form.name.trim() && m.name.toLowerCase().includes(form.name.trim().toLowerCase()))

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
      <div className="text-xs text-slate-500 mb-1">Сырьё</div>
      {value.length === 0 && (
        <div className="text-sm text-slate-400 mb-1">На этой линии сырьё ещё не заведено.</div>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {value.map(m => (
            <span key={m.id}
              className={`badge cursor-pointer ${editingId === m.id ? 'bg-teal-100 text-teal-800' : 'bg-teal-50 text-teal-800 hover:bg-teal-100'}`}
              onClick={() => startEdit(m)} title="Клик — редактировать">
              {m.name} — {m.quantity.toLocaleString('ru-RU')} {m.unit}
              <button type="button" className="ml-1 text-teal-500 hover:text-red-600"
                onClick={ev => { ev.stopPropagation(); remove(m.id) }}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <div className="relative flex-1" ref={nameRef}>
          <input className="w-full border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
            placeholder="напр.: вкрапленная руда"
            value={form.name}
            onFocus={() => setNameOpen(true)}
            onChange={e => { setForm({ ...form, name: e.target.value }); setNameOpen(true) }} />
          {nameOpen && suggestions.length > 0 && (
            <div className="absolute z-20 mt-1 w-full bg-white border border-slate-300 rounded shadow-lg
                max-h-48 overflow-auto text-sm">
              {suggestions.map(s => (
                <button key={s.id} type="button" className="w-full text-left px-2 py-1 hover:bg-teal-50"
                  onClick={() => { setForm({ ...form, name: s.name }); setNameOpen(false) }}>
                  {s.name}
                </button>
              ))}
            </div>
          )}
        </div>
        <input type="number" min={0} className="w-24 border border-slate-300 rounded px-2 py-1 text-sm placeholder:text-slate-400"
          placeholder="кол-во" value={form.quantity}
          onChange={e => setForm({ ...form, quantity: e.target.value })} />
        <select className="w-20 border border-slate-300 rounded px-2 py-1 text-sm"
          value={form.unit} onChange={e => setForm({ ...form, unit: e.target.value as MaterialUnit })}>
          {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
        </select>
        <button type="button" className="btn" disabled={busy || !form.name.trim() || form.quantity === ''}
          onClick={submit}>
          {editingId ? 'Сохранить' : '+ Добавить'}
        </button>
        {editingId && <button type="button" className="btn" onClick={cancelEdit}>Отмена</button>}
      </div>
    </div>
  )
}
