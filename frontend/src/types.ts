// Зеркала pydantic-моделей бэкенда (без строгой полноты)
export interface Project {
  id: string; plant: string; goal: string; constraints: string;
  created_at: string; weights: Record<string, number>; stoplist: string[];
  has_report?: boolean; hypotheses_count?: number;
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
  quote: string; source: string; page: number | null; chunk_id: string | null; verified: boolean;
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
}

export interface ChatReference { type: 'rule' | 'cell' | 'hypothesis' | 'chunk'; id: string }
export interface ChatAnswer { text: string; references: ChatReference[] }

export interface KbDoc { doc_id: string; source: string; pages: number; chunks: number; status: string }
export interface KbHit {
  chunk_id: string; text: string; source: string; page: number; score: number;
}
