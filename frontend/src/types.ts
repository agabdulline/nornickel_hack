// Зеркала pydantic-моделей бэкенда (без строгой полноты)
export interface Equipment {
  id: string; line_id: string; name: string; position: string;
  category: string; status: 'в эксплуатации' | 'резерв' | 'выведено';
}

export type LineKind = 'фабрика' | 'производственная линия' | 'лаборатория';
export type LineOwnership = 'в штате компании' | 'внешний подрядчик/партнёр';

export interface Line {
  id: string; name: string; kind: LineKind; ownership: LineOwnership;
}

export interface Material {
  id: string; name: string;
}

// свободная строка — стандартный список предлагается в UI (см. STANDARD_UNITS
// в components/lines.tsx), но «своя единица…» допускает произвольный текст
export type MaterialUnit = string;

export interface LineMaterial {
  id: string; line_id: string; material_id: string; name: string;
  quantity: number; unit: MaterialUnit;
}

export interface ProjectConstraints {
  equipment: Equipment[];
  materials: LineMaterial[];
}

// Отклонённое направление на уровне линии (память фидбэка) — см. «Базу знаний»
export interface StopEntry {
  id: string; line_id: string; direction: string; reason: string;
  project_id?: string | null; hypothesis_id?: string | null; created_at?: string;
}

export interface Project {
  id: string; name: string; plant: string; goal: string; constraints: string;
  material?: string;  // исследуемый материал (по умолчанию «отвальные хвосты»)
  created_at: string; weights: Record<string, number>; stoplist: string[];
  project_constraints?: ProjectConstraints;
  has_report?: boolean; hypotheses_count?: number;
  accepted_count?: number; roadmap_built?: boolean;
}

export interface DataIssue {
  severity: 'info' | 'warning' | 'error'; message: string;
  cell?: string | null; rule?: string | null;
}

export interface SizeClassRow {
  label: string; share_pct: number | null;
  element_share_pct: Record<string, number | null>;
  element_tonnes: Record<string, number | null>;
}

export interface LossCell {
  axes: { size_class: string; mineral_form: string };
  element: 'Ni' | 'Cu'; tonnes: number | null; share_pct: number | null;
  recoverable: boolean; process_area: string | null;
  provenance: 'measured' | 'recovered_math' | 'recovered_llm' | 'manual';
  confidence: number | null; recovery_note: string | null;
}

export interface TailingsReport {
  plant: string; tail_type: string; feed_tonnes: number | null; tails_tonnes: number | null;
  grade: Record<string, number>; losses_tonnes: Record<string, number>;
  size_classes: SizeClassRow[]; cells: LossCell[];
  recoverable_total: Record<string, number>; recoverable_pct: Record<string, number>;
  issues: DataIssue[];
}

export interface Diagnosis {
  rule_id: string; zone: string; title: string; text: string; element: 'Ni' | 'Cu';
  inputs: Record<string, unknown>; cell_keys: string[];
  tonnes_recoverable: number; uncertain: boolean;
  node_refs?: string[]; regime_line?: string | null;
}

export interface FlowsheetNode {
  id: string; name: string; type: string;
  t_min?: string | number | null; pct_solids?: number | null;
  reagents?: Record<string, number> | null;
  equipment_positions?: string[] | null;
}

export interface FlowsheetStream {
  from: string; to: string; kind: string; name?: string | null;
  gamma?: number | null; beta_cu?: number | null; beta_ni?: number | null;
  eps_cu?: number | null; eps_ni?: number | null;
}

export interface FlowsheetData {
  source_files?: string[];
  nodes: FlowsheetNode[];
  streams: FlowsheetStream[];
}

export interface DiagnosticsResult {
  tail_type?: string;
  diagnoses: Diagnosis[];
  not_proposed: { rule_id: string; element: string; form: string; tonnes: number; reason: string }[];
  issues: DataIssue[];
  loss_map: Record<string, Record<string, Record<string, {
    tonnes: number; share_pct: number | null; recoverable: boolean;
    provenance: string; process_area: string | null }>>>;
  report_issues?: DataIssue[];
}

export interface Citation {
  quote: string; quote_ru?: string | null; source: string;
  page: number | null; chunk_id: string | null; verified: boolean;
}

export interface Step {
  n: number; action: string; resources: string; duration: string;
  success_criterion: string; fail_criterion: string;
}

export interface Hypothesis {
  id: string; title: string; process_area: string; element: 'Ni' | 'Cu';
  hypothesis_type: string;
  target_cells: { key: string; tonnes: number | null }[];
  mechanism: string; rationale: Citation[];
  equipment: { name: string; positions: string[]; present_on_plant: boolean }[];
  effect: { tonnes_max: number; tonnes_expected: number; money_usd: number; assumptions: string };
  risks: string[]; feasibility: Record<string, unknown>;
  novelty: { score?: number; prior_matches?: string[] };
  verification_plan: Step[]; score: number; status: string;
  diagnosis_rule: string | null; uncertain: boolean;
}

export interface RoadmapItem {
  id: string; hypothesis_id: string; hypothesis_title: string;
  stage: 'lab' | 'pilot' | 'rollout'; start: string; end: string;
  resource: string | null; gate_criterion: string | null;
  depends_on: string[]; shifted_reason: string | null;
  manual_conflict?: boolean; conflict_with?: string[];
}

export interface ChatReference { type: 'rule' | 'cell' | 'hypothesis' | 'chunk'; id: string }
export interface ChatChart {
  type: 'bar'
  title: string
  unit?: string
  data: { label: string; value: number }[]
}
export interface ChatAction {
  type: 'accept_hypothesis' | 'reject_hypothesis' | 'set_weights' | 'build_roadmap'
  params: { id?: string; title?: string; reason?: string; weights?: Record<string, number> }
  label: string
}
export interface ChatAnswer {
  text: string; references: ChatReference[]; charts?: ChatChart[]
  actions?: ChatAction[]; followups?: string[]
}
export interface ChatMeta {
  id: string; project_id: string; title: string
  created_at: string; updated_at: string; messages: number
}

export interface KbDoc {
  doc_id: string; source: string; pages: number; chunks: number; status: string;
  ocr_done?: number; error?: string;
  lang?: 'ru' | 'en' | 'zh'; enabled?: boolean; topic?: string;
}
export interface FactoryImage {
  id: string; factory: string; filename: string; caption: string;
  path: string; created_at: string;
}
export interface FactoryInfo { factory: string; digitized: boolean; images: FactoryImage[] }

export interface ProjectFile {
  id: string; project_id: string; filename: string;
  kind: 'scheme' | 'image' | 'pdf' | 'text' | 'other';
  status: string; chars: number; preview: string; created_at: string;
}

export interface KbHit {
  chunk_id: string; text: string; source: string; page: number; score: number;
}
