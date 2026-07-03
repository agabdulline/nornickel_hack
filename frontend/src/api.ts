import type {
  ChatAnswer, DiagnosticsResult, FlowsheetData, Hypothesis, KbDoc, Project, RoadmapItem,
  TailingsReport,
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
  createProject: (body: { plant: string; goal?: string; constraints?: string; factory?: string }) =>
    j<Project>(fetch('/api/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })),

  flowsheet: (pid: string) =>
    j<{ factory: string | null; flowsheet: FlowsheetData | null;
        rule_node_types?: Record<string, string[]> }>(
      fetch(`/api/projects/${pid}/flowsheet`)),

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
