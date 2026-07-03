import type {
  ChatAnswer, DiagnosticsResult, Equipment, Hypothesis, KbDoc, Line, LineMaterial, Material,
  Project, ProjectConstraints, RoadmapItem, TailingsReport,
} from './types'

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
    plant: string; name?: string; goal?: string; constraints?: string
    project_constraints?: ProjectConstraints
  }) =>
    j<Project>(fetch('/api/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),

  // ---------- линии/лаборатории (мастер-данные) ----------
  lines: () => j<Line[]>(fetch('/api/lines')),
  createLine: (body: { name: string; type: 'factory' | 'lab' }) =>
    j<Line>(fetch('/api/lines', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),
  updateLine: (id: string, body: { name?: string; type?: 'factory' | 'lab' }) =>
    j<Line>(fetch(`/api/lines/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),

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
  hypotheses: (pid: string) => j<Hypothesis[]>(fetch(`/api/projects/${pid}/hypotheses`)),
  feedback: (hid: string, action: 'accept' | 'reject', reason = '') =>
    j<{ status: string; stoplist: string[] }>(fetch(`/api/hypotheses/${hid}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, reason }),
    })),

  chat: (pid: string, message: string, history: { role: string; content: string }[]) =>
    j<ChatAnswer>(fetch(`/api/projects/${pid}/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
    })),

  roadmapBuild: (pid: string) =>
    j<RoadmapItem[]>(fetch(`/api/projects/${pid}/roadmap/build`, { method: 'POST' })),
  roadmap: (pid: string) => j<RoadmapItem[]>(fetch(`/api/projects/${pid}/roadmap`)),
  roadmapMove: (itemId: string, start: string) =>
    j<{ items: RoadmapItem[] }>(fetch(`/api/roadmap/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start }),
    })),

  kbDocs: () => j<KbDoc[]>(fetch('/api/kb/documents')),
  kbUpload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<KbDoc>(fetch('/api/kb/upload', { method: 'POST', body: fd }))
  },
  kbAsk: (question: string) =>
    j<{ answer: string; citations: { chunk_id: string; source: string; page: number; quote: string }[] }>(
      fetch('/api/kb/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })),
  kbChunk: (chunkId: string) =>
    j<{ chunk_id: string; text: string; source: string; page_start: number }>(
      fetch(`/api/kb/chunk/${encodeURIComponent(chunkId)}`)),
}

export const fmt = {
  t: (v: number | null | undefined, digits = 1) =>
    v == null ? '—' : v.toLocaleString('ru-RU', { maximumFractionDigits: digits }),
  pct: (v: number | null | undefined, digits = 1) =>
    v == null ? '—' : `${v.toLocaleString('ru-RU', { maximumFractionDigits: digits })}%`,
  usd: (v: number | null | undefined) =>
    v == null ? '—' : `$${Math.round(v).toLocaleString('ru-RU')}`,
}
