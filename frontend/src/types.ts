export type Role = "invoice" | "reference";

export interface Labels {
  match_status: Record<string, string>;
  validation_status: Record<string, string>;
  review_status: Record<string, string>;
  category: Record<string, string>;
  field_status: Record<string, string>;
  file_status: Record<string, string>;
}

export interface FieldDef {
  name: string;
  label: string;
  type: string;
  required: boolean;
  aliases: string[];
  description?: string;
}

export interface RoleDef {
  label: string;
  plural: string;
  description: string;
  accepts: string[];
}

export interface RuleDef {
  id: string;
  type: string;
  label: string;
  severity: string;
  applies_to: string[];
  fields?: string[];
  addends?: string[];
  total?: string;
  tolerance?: string;
  field?: string;
  allow_negative?: boolean;
}

export interface TemplateSummary {
  id: string;
  version: number;
  name: string;
  description: string;
  synthetic_note: string;
  roles: Record<Role, RoleDef>;
  fields: FieldDef[];
  dates: { default_order: string };
  currency: {
    default: string | null;
    allowed: string[];
    symbols: Record<string, string>;
    markers: Record<string, string>;
    minor_units: Record<string, number>;
  };
  party_normalization: {
    legal_suffixes: string[];
    aliases: Record<string, string[]>;
  };
  validation_rules: RuleDef[];
  matching: { identity_fields: string[]; compare: { field: string; tolerance: string }[] };
  pdf_layouts: string[];
  pdf_layout_details: { id: string; name: string; description: string; date_order: string; date_order_label: string }[];
  date_order_labels: Record<string, string>;
  summary_columns: { name: string; label: string }[];
  labels: Labels;
}

export interface Meta {
  version: string;
  labels: Labels;
  templates: TemplateSummary[];
  limits: { max_upload_mb: number; max_files_per_upload: number };
}

export interface ImportGap {
  file_id: number;
  file_name: string;
  role: Role;
  status: string;
  status_label: string;
  reason: string;
}

export interface Counts {
  completeness: { complete: boolean; gaps: ImportGap[] };
  files: Record<string, number> & { total: number };
  invoices: number;
  references: number;
  match: Record<Role, Record<string, number>>;
  validation: Record<string, number>;
  review: Record<string, number>;
  reference_review: Record<string, number>;
  open_issues: number;
  open_exception_records: number;
  progress: { decided: number; total: number };
  rejected_files: number;
  needs_mapping: number;
  pending_files: number;
}

export interface BatchSummary {
  id: number;
  name: string;
  template_id: string;
  template_version: number;
  template_name: string;
  sample_id: string | null;
  created_at: string;
  updated_at: string;
  last_processed_at: string | null;
  counts: Counts;
}

export interface FileInfo {
  id: number;
  batch_id: number;
  role: Role;
  original_name: string;
  kind: string | null;
  size_bytes: number;
  sha256: string | null;
  status: string;
  status_detail: string | null;
  rejection_code: string | null;
  layout_id: string | null;
  page_count: number | null;
  sheet_name: string | null;
  header_row: number | null;
  mapping: Record<string, string | null> | null;
  date_order: string | null;
  default_currency: string | null;
  mapping_profile_id: number | null;
  record_count: number;
  uploaded_at: string;
  processed_at: string | null;
  removed_at: string | null;
  identical_to?: string | null;
}

export interface BatchDetail extends BatchSummary {
  files: FileInfo[];
}

export interface FieldBrief {
  display: string | null;
  current: string | null;
  status: string;
  error: string | null;
}

export interface RecordSummary {
  id: number;
  role: Role;
  file_id: number;
  file_name: string;
  source_ref: string;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  total_amount: string | null;
  fields: Record<string, FieldBrief>;
  validation_status: string;
  match_status: string;
  match_summary: string | null;
  partner_id: number | null;
  review_status: string;
  corrected: boolean;
  issue_count: number;
  error_count: number;
  categories: string[];
  updated_at: string;
}

export interface FieldState {
  name: string;
  label: string;
  type: string;
  original: string | null;
  current: string | null;
  status: string;
  display: string | null;
  normalized: string | null;
  error: string | null;
  key: string | null;
  marker_currency: string | null;
  ambiguous: boolean;
}

export interface Check {
  rule_id: string;
  rule_type: string;
  label: string;
  status: "passed" | "issue" | "not_checked";
  severity: string;
  message: string;
  field: string | null;
  category: string | null;
}

export interface Issue {
  id: number;
  kind: string;
  category: string;
  rule_id: string | null;
  field: string | null;
  severity: string;
  message: string;
}

export interface Comparison {
  field: string;
  label: string;
  record_value: string | null;
  reference_value: string | null;
  status: string;
  difference: string | null;
  message: string | null;
}

export interface MatchInfo {
  status: string;
  partner_id: number | null;
  method: string | null;
  explanation: string[];
  comparisons: Comparison[];
  candidates: number[];
  hints: string[];
  no_reference_rows: boolean;
}

export interface HistoryEntry {
  id: number;
  batch_id: number;
  record_id: number | null;
  file_id: number | null;
  action: string;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  actor: string;
  created_at: string;
  record_ref?: string | null;
  file_name?: string | null;
}

export interface Evidence {
  page?: number;
  line?: number;
  text?: string;
  cell?: string;
  column?: string;
}

export interface RecordDetail extends Omit<RecordSummary, "fields"> {
  batch_id: number;
  template_id: string;
  file_kind: string;
  layout_id: string | null;
  extraction_method: string;
  date_order: string;
  date_order_label: string;
  field_defs: FieldDef[];
  fields: Record<string, FieldState>;
  extracted: Record<string, { value: string | null; kind: string; evidence: Evidence | null }>;
  corrections: Record<string, string>;
  checks: Check[];
  issues: Issue[];
  match: MatchInfo;
  partner: RecordSummary | null;
  candidates: RecordSummary[];
  manual_link: { record_id: number; reference_id: number; created_at: string } | null;
  source_cells: Record<string, string | null> | null;
  pages: { page_no: number; text: string }[];
  notes: string[];
  review_reason: string | null;
  reviewed_at: string | null;
  history: HistoryEntry[];
  role_label: string;
}

export interface Profile {
  id: number;
  name: string;
  template_id: string;
  role: Role;
  header_signature: string;
  headers: string[];
  mapping: Record<string, string | null>;
  date_order: string;
  default_currency: string | null;
}

export interface DateAnalysis {
  values: number;
  DMY: number;
  MDY: number;
  YMD: number;
  ambiguous_numeric: number;
  date_cells: number;
  field: string;
}

export interface Preview {
  sheets: string[];
  sheet: string | null;
  header_row: number;
  headers: string[];
  rows: { row: number; cells: (string | null)[] }[];
  total_rows: number;
  over_limit: boolean;
  row_limit: number;
  notes: string[];
  date_analysis: DateAnalysis | null;
  signature: string;
  file: FileInfo;
  suggestions: Record<string, { column: string | null; reason: string | null }>;
  proposed_mapping: Record<string, string | null>;
  proposed_from: string;
  profiles: Profile[];
  matching_profile_id: number | null;
  date_order: string;
  default_currency: string | null;
  date_order_labels: Record<string, string>;
  fields: FieldDef[];
  allowed_currencies: string[];
}

export interface Sample {
  id: string;
  name: string;
  description: string;
  template_id: string;
  file_count: number;
}

export interface SampleLoadResult {
  batch_id: number;
  auto_mapped: string[];
  waiting_for_mapping: string[];
  summary: Counts;
}

export interface ProcessResult extends Counts {
  processed_files: number;
  waiting_for_mapping: string[];
  approvals_withdrawn: number[];
}
