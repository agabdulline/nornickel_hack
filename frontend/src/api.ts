import type {
  ChatAnswer, ChatChart, ChatMeta, ChatReference, DiagnosticsResult, Equipment, FactoryImage,
  FactoryInfo, ProjectFile,
  FlowsheetData, Hypothesis, KbDoc, Line, LineMaterial, Material, Project,
  ProjectConstraints, RoadmapItem, StopEntry, TailingsReport,
} from './types'

export interface ChatHistoryMsg {
  role: 'user' | 'assistant'
  content: string
  references: ChatReference[]
  charts?: ChatChart[]
  created_at?: string
}

async function j<T>(pending: Promise<Response>): Promise<T> {
  const resp = await pending
  if (!resp.ok) {
    let detail = resp.statusText
    try { detail = (await resp.json()).detail ?? detail } catch { /* пусто */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  health: () => j<{ status: string; llm_configured: boolean }>(fetch('/api/health')),

  projects: () => j<Project[]>(fetch('/api/projects')),
  project: (id: string) => j<Project>(fetch(`/api/projects/${id}`)),
  createProject: (body: {
    plant: string; name?: string; goal?: string; constraints?: string; factory?: string
    material?: string
    project_constraints?: ProjectConstraints
  }) =>
    j<Project>(fetch('/api/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  deleteProject: (id: string) =>
    j<{ ok: boolean }>(fetch(`/api/projects/${id}`, { method: 'DELETE' })),

  flowsheet: (pid: string) =>
    j<{ factory: string | null; flowsheet: FlowsheetData | null;
        rule_node_types?: Record<string, string[]> }>(
      fetch(`/api/projects/${pid}/flowsheet`)),

  // ---------- линии/лаборатории (мастер-данные) ----------
  lines: () => j<Line[]>(fetch('/api/lines')),
  createLine: (body: { name: string; kind?: string; ownership?: string }) =>
    j<Line>(fetch('/api/lines', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  updateLine: (id: string, body: { name?: string; kind?: string; ownership?: string }) =>
    j<Line>(fetch(`/api/lines/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),

  // ---------- стоп-лист линии (память фидбэка по объекту) ----------
  lineStoplist: (lineId: string) =>
    j<StopEntry[]>(fetch(`/api/lines/${encodeURIComponent(lineId)}/stoplist`)),
  deleteLineStop: (id: string) =>
    j<{ ok: boolean }>(fetch(`/api/line-stoplist/${encodeURIComponent(id)}`, { method: 'DELETE' })),

  // ---------- справочник материалов ----------
  materials: () => j<Material[]>(fetch('/api/materials')),
  createMaterial: (name: string) =>
    j<Material>(fetch('/api/materials', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })),

  // ---------- сырьё линии ----------
  lineMaterials: (lineId: string) =>
    j<LineMaterial[]>(fetch(`/api/line-materials?line_id=${encodeURIComponent(lineId)}`)),
  addLineMaterial: (body: {
    line_id: string; name: string; quantity: number; unit: string; material_id?: string
  }) =>
    j<LineMaterial>(fetch('/api/line-materials', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  updateLineMaterial: (id: string, body: {
    quantity?: number; unit?: string; name?: string; material_id?: string
  }) =>
    j<LineMaterial>(fetch(`/api/line-materials/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  deleteLineMaterial: (id: string) =>
    j<{ ok: boolean }>(fetch(`/api/line-materials/${id}`, { method: 'DELETE' })),

  equipmentForLine: (lineId: string) =>
    j<Equipment[]>(fetch(`/api/equipment?line_id=${encodeURIComponent(lineId)}`)),
  addEquipment: (body: { line_id: string; name: string; position?: string; category?: string }) =>
    j<Equipment>(fetch('/api/equipment', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  updateEquipment: (id: string, body: {
    name?: string; position?: string; category?: string; status?: string
  }) =>
    j<Equipment>(fetch(`/api/equipment/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  deleteEquipment: (id: string) =>
    j<{ ok: boolean }>(fetch(`/api/equipment/${id}`, { method: 'DELETE' })),

  uploadReport: (pid: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<{ reports: TailingsReport[]; recover_stats: Record<string, unknown>[] }>(
      fetch(`/api/projects/${pid}/report`, { method: 'POST', body: fd }))
  },
  report: (pid: string) => j<{ reports: TailingsReport[] }>(fetch(`/api/projects/${pid}/report`)),
  patchCells: (pid: string, edits: { key: string; tonnes?: number; share_pct?: number }[],
               tail_type?: string) =>
    j<{ applied: number; report: TailingsReport }>(fetch(`/api/projects/${pid}/report/cells`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tail_type, edits }),
    })),

  diagnostics: (pid: string, tailType?: string) =>
    j<DiagnosticsResult>(fetch(`/api/projects/${pid}/diagnostics` +
      (tailType ? `?tail_type=${encodeURIComponent(tailType)}` : ''))),

  generate: (pid: string, body: {
    weights?: Record<string, number>; excluded_areas?: string[];
    constraints?: string; tail_type?: string
  }) =>
    j<Hypothesis[]>(fetch(`/api/projects/${pid}/hypotheses/generate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  rerank: (pid: string, weights: Record<string, number>) =>
    j<Hypothesis[]>(fetch(`/api/projects/${pid}/hypotheses/rerank`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ weights }),
    })),
  hypotheses: (pid: string) => j<Hypothesis[]>(fetch(`/api/projects/${pid}/hypotheses`)),
  feedback: (hid: string, action: 'accept' | 'reject', reason = '') =>
    j<{ status: string; line_stoplist: StopEntry[] }>(fetch(`/api/hypotheses/${hid}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, reason }),
    })),
  // перенос гипотезы между колонками канбана (Отчёт) — только смена статуса
  setHypothesisStatus: (hid: string, status: string) =>
    j<{ id: string; status: string }>(fetch(`/api/hypotheses/${hid}/status`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })),

  // историю хранит сервер (по диалогам) — клиент шлёт вопрос, chat_id
  // и текущий экран (report|map|hypotheses|export) для вопросов «здесь/на этой странице»
  chat: (pid: string, message: string, chatId?: string, page?: string) =>
    j<ChatAnswer & { chat_id: string }>(fetch(`/api/projects/${pid}/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, chat_id: chatId, page }),
    })),
  chats: (pid: string) => j<ChatMeta[]>(fetch(`/api/projects/${pid}/chats`)),
  chatCreate: (pid: string) =>
    j<ChatMeta>(fetch(`/api/projects/${pid}/chats`, { method: 'POST' })),
  chatDelete: (pid: string, chatId: string) =>
    j<{ ok: boolean }>(fetch(`/api/projects/${pid}/chats/${encodeURIComponent(chatId)}`, {
      method: 'DELETE',
    })),
  chatClear: (pid: string) =>
    j<{ cleared: number }>(fetch(`/api/projects/${pid}/chat/history`, { method: 'DELETE' })),
  chatHistory: (pid: string, chatId?: string) =>
    j<{ chat_id: string | null; messages: ChatHistoryMsg[] }>(
      fetch(`/api/projects/${pid}/chat/history` +
        (chatId ? `?chat_id=${encodeURIComponent(chatId)}` : ''))),

  // ---------- схемы фабрик (БД) и материалы проекта ----------
  factories: () => j<FactoryInfo[]>(fetch('/api/factories')),
  factoryFlowsheet: (factory: string) =>
    j<{ factory: string; flowsheet: FlowsheetData | null
        status?: string; source?: string; error?: string }>(
      fetch(`/api/factories/${encodeURIComponent(factory)}/flowsheet`)),
  lineFlowsheetUpload: (lineId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<{ key: string; status: string }>(
      fetch(`/api/lines/${encodeURIComponent(lineId)}/flowsheet-image`, {
        method: 'POST', body: fd,
      }))
  },
  factoryImageUpload: (factory: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<FactoryImage>(fetch(`/api/factories/${encodeURIComponent(factory)}/images`, {
      method: 'POST', body: fd,
    }))
  },
  factoryImagePatch: (id: string, caption: string) =>
    j<FactoryImage>(fetch(`/api/factory-images/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caption }),
    })),
  factoryImageDelete: (id: string) =>
    j<{ ok: boolean }>(fetch(`/api/factory-images/${id}`, { method: 'DELETE' })),
  factoryImageUrl: (id: string) => `/api/factory-images/${id}/file`,

  projectFiles: (pid: string) => j<ProjectFile[]>(fetch(`/api/projects/${pid}/files`)),
  projectFileUpload: (pid: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<ProjectFile>(fetch(`/api/projects/${pid}/files`, { method: 'POST', body: fd }))
  },
  projectFileDelete: (pid: string, fid: string) =>
    j<{ ok: boolean }>(fetch(`/api/projects/${pid}/files/${fid}`, { method: 'DELETE' })),
  projectFileUrl: (pid: string, fid: string) => `/api/projects/${pid}/files/${fid}/file`,

  roadmapBuild: (pid: string) =>
    j<RoadmapItem[]>(fetch(`/api/projects/${pid}/roadmap/build`, { method: 'POST' })),
  roadmap: (pid: string) => j<RoadmapItem[]>(fetch(`/api/projects/${pid}/roadmap`)),
  // При конфликте бросает Error с полем .kind (resource|order|past|notfound);
  // detail-объект нельзя гнать через j(), поэтому разбираем ответ вручную.
  roadmapMove: async (itemId: string, start: string, force = false): Promise<{ items: RoadmapItem[] }> => {
    const resp = await fetch(`/api/roadmap/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start, force }),
    })
    if (resp.ok) return resp.json()
    let kind = '', message = resp.statusText
    try {
      const d = (await resp.json()).detail
      if (d && typeof d === 'object') { kind = d.kind ?? ''; message = d.message ?? message }
      else if (typeof d === 'string') message = d
    } catch { /* пусто */ }
    const err = new Error(message) as Error & { kind: string }
    err.kind = kind
    throw err
  },

  kbDocs: () => j<KbDoc[]>(fetch('/api/kb/documents')),
  kbUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<KbDoc>(fetch('/api/kb/upload', { method: 'POST', body: fd }))
  },
  kbDocPreview: (docId: string, offset = 0, limit = 6) =>
    j<{
      doc_id: string; source: string; pages: number; status: string
      total_chunks: number; offset: number; has_file?: boolean
      chunks: { chunk_id: string; page_start: number; page_end: number; text: string }[]
    }>(fetch(`/api/kb/documents/${encodeURIComponent(docId)}/preview?offset=${offset}&limit=${limit}`)),
  kbPatchDoc: (docId: string, body: { enabled?: boolean; topic?: string }) =>
    j<KbDoc>(fetch(`/api/kb/documents/${encodeURIComponent(docId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  kbSetEnabled: (docId: string, enabled: boolean) =>
    j<KbDoc>(fetch(`/api/kb/documents/${encodeURIComponent(docId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })),
  kbDelete: (docId: string) =>
    j<{ deleted: string }>(fetch(`/api/kb/documents/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
    })),
  kbAsk: (question: string) =>
    j<{ answer: string; citations: { chunk_id: string; source: string; page: number; quote: string }[] }>(
      fetch('/api/kb/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })),
  // ассистент БЗ на главной: те же серверные диалоги, что у проектного
  kbChats: () => j<ChatMeta[]>(fetch('/api/kb/chats')),
  kbChatCreate: () => j<ChatMeta>(fetch('/api/kb/chats', { method: 'POST' })),
  kbChatDelete: (chatId: string) =>
    j<{ ok: boolean }>(fetch(`/api/kb/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' })),
  kbChatHistory: (chatId?: string) =>
    j<{ chat_id: string | null; messages: ChatHistoryMsg[] }>(
      fetch('/api/kb/chat/history' + (chatId ? `?chat_id=${encodeURIComponent(chatId)}` : ''))),
  kbChat: (question: string, chatId?: string) =>
    j<{ answer: string; chat_id: string
        citations: { chunk_id: string; source: string; page: number; quote: string }[] }>(
      fetch('/api/kb/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, chat_id: chatId }),
      })),
  kbChunk: (chunkId: string) =>
    j<{
      chunk_id: string; doc_id: string; text: string; source: string
      page_start: number; page_end?: number; has_file?: boolean; lang?: string
    }>(fetch(`/api/kb/chunk/${encodeURIComponent(chunkId)}`)),
  kbTranslate: (chunkIds: string[]) =>
    j<{ translations: Record<string, string> }>(fetch('/api/kb/translate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunk_ids: chunkIds }),
    })),
}

/** Курс отображения денежного эффекта. Внутри данные в USD (биржевые цены
 *  металлов), в UI/отчётах — рубли. Актуальный курс ЦБ приходит с /api/fx;
 *  до ответа (или офлайн) — запасной курс, синхронный с rub_per_usd
 *  в domain_packs/flotation.yaml. */
export const fx = { rate: 90, date: null as string | null, source: 'default' }

/** Промис загрузки курса: экраны с деньгами делают re-render по завершении. */
export const fxReady: Promise<void> = (async () => {
  try {
    const r = await j<{ rub_per_usd: number; date: string | null; source: string }>(
      fetch('/api/fx'))
    fx.rate = r.rub_per_usd; fx.date = r.date; fx.source = r.source
  } catch { /* офлайн — остаёмся на запасном курсе */ }
})()

/** Подпись курса: «79,4 ₽/$ · ЦБ РФ на 04.07.2026» или «90 ₽/$ · курс по умолчанию». */
export const fxLabel = () => {
  const rate = fx.rate.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
  if (fx.source === 'cbr' && fx.date) {
    const [y, m, d] = fx.date.split('-')
    return `${rate} ₽/$ · ЦБ РФ на ${d}.${m}.${y}`
  }
  return `${rate} ₽/$ · курс по умолчанию`
}

export const fmt = {
  t: (v: number | null | undefined, digits = 1) =>
    v == null ? '—' : v.toLocaleString('ru-RU', { maximumFractionDigits: digits }),
  pct: (v: number | null | undefined, digits = 1) =>
    v == null ? '—' : `${v.toLocaleString('ru-RU', { maximumFractionDigits: digits })}%`,
  /** Эффект в ₽ из внутреннего USD-значения: конвертация по курсу, млн/млрд. */
  rub: (usd: number | null | undefined) => {
    if (usd == null) return '—'
    const r = usd * fx.rate
    if (Math.abs(r) >= 1e9)
      return `${(r / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млрд ₽`
    if (Math.abs(r) >= 1e6)
      return `${Math.round(r / 1e6).toLocaleString('ru-RU')} млн ₽`
    return `${Math.round(r).toLocaleString('ru-RU')} ₽`
  },
  /** Исходная сумма в долларах (биржевые цены металлов, USD/т). */
  usd: (v: number | null | undefined) => {
    if (v == null) return '—'
    const a = Math.abs(v)
    if (a >= 1e9) return `$${(v / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млрд`
    if (a >= 1e6) return `$${(v / 1e6).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млн`
    if (a >= 1e3) return `$${Math.round(v / 1e3).toLocaleString('ru-RU')} тыс`
    return `$${Math.round(v).toLocaleString('ru-RU')}`
  },
}
