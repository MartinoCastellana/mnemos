export type Audit = {
  id: number;
  stage: string;
  agent: string;
  action: string;
  detail: Record<string, unknown>;
  created_at: string;
};
export type Result = {
  field_key: string;
  value: string | null;
  confidence: number;
  page_number: number | null;
  bbox: number[] | null;
  evidence: string;
  reasoning: string[];
  validated_by: string;
  candidates: Array<Record<string, unknown>>;
};
export type Page = {
  page_number: number;
  render_url: string | null;
};
export type Document = {
  id: string;
  filename: string;
  page_count: number;
  status: string;
  pipeline_mode: string;
  error: string | null;
  created_at: string;
  updated_at: string;
};
export type FieldDefinition = {
  id: number;
  key: string;
  label: string;
  instructions: string;
  positive_examples: string[];
  negative_examples: string[];
  validator: Record<string, unknown>;
  ranking_rules: Array<Record<string, unknown>>;
  strategy: Record<string, unknown>;
  enabled: boolean;
};
export type ProcessingStatus = {
  id: string;
  status: string;
  error: string | null;
  page_count: number;
  completed_pages: number;
  run_id: string | null;
  latest_audit_id: number | null;
};
export type Detail = Document & { pages: Page[]; results: Result[]; audits: Audit[] };
export type DocumentMemory = {
  pipeline_version: string;
  run: {
    id: string;
    status: string;
    pipeline_version: string;
    model_name: string;
    started_at: string;
    completed_at: string | null;
    error: string | null;
  } | null;
  candidates: Array<{
    id: number;
    field_key: string;
    raw_value: string;
    normalized_value: string;
    page_number: number;
    bounding_box: number[] | null;
    chunk_id: string | null;
    semantic_role: string;
    semantic_confidence: number;
    ocr_confidence: number;
    vision_confidence: number;
    source_engine: string;
    evidence_text: string;
    requires_review: boolean;
    selected: boolean;
    rejection_reason: string | null;
  }>;
  resolved_fields: Array<{
    field_key: string;
    value: string | null;
    selected_candidate_id: number | null;
    confidence: number;
    source_page: number | null;
    selection_reason: string[];
    requires_review: boolean;
  }>;
  micro_memories: Array<{
    page_number: number;
    document_assignment: string;
    document_type: string;
    page_type: string;
    page_type_confidence: number;
    continuation_confidence: number;
    starts_new_document: boolean;
    new_document_confidence: number;
    page_summary: string;
    entity_candidates: unknown[];
    requires_review: boolean;
  }>;
  entity_clusters: Array<{
    id: number;
    field_key: string;
    representative_value: string;
    semantic_role: string;
    candidate_ids: number[];
    page_numbers: number[];
    document_assignments: string[];
    global_confidence: number;
    has_conflict: boolean;
  }>;
  relationships: Array<{
    id: number;
    relation_type: string;
    source_candidate_id: number;
    target_candidate_id: number;
    page_number: number | null;
    confidence: number;
    evidence: string;
  }>;
};
export type RunAnalytics = {
  run_id: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  page_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  candidate_count: number;
  resolved_count: number;
  vision_pages: number;
  phases: Array<{
    phase: string;
    duration_ms: number;
    prompt_tokens: number;
    completion_tokens: number;
    calls: number;
  }>;
  pages: Array<{
    page_number: number;
    duration_ms: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    vision_used: boolean;
    candidate_count: number;
    requires_review: boolean;
  }>;
};

const json = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, init);
  if (!response.ok)
    throw new Error((await response.json().catch(() => ({ detail: response.statusText }))).detail);
  return response.json();
};
export const api = {
  documents: () => json<Document[]>("/api/documents"),
  fields: () => json<FieldDefinition[]>("/api/fields"),
  detail: (id: string) => json<Detail>(`/api/documents/${id}`),
  memory: (id: string) => json<DocumentMemory>(`/api/documents/${id}/memory`),
  runAnalytics: (id: string) => json<RunAnalytics[]>(`/api/documents/${id}/runs/analytics`),
  status: (id: string) => json<ProcessingStatus>(`/api/documents/${id}/status`),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return json<Document>("/api/documents", { method: "POST", body });
  },
  process: (id: string, mode: string) =>
    json(`/api/documents/${id}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }),
  processPending: (mode: string) =>
    json<{ status: string; count: number; document_ids: string[] }>(
      "/api/documents/process-pending",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      },
    ),
  resetDocument: (id: string) =>
    json<{ id: string; status: string }>(`/api/documents/${id}/results`, { method: "DELETE" }),
  updateResult: (id: string, fieldKey: string, value: string | null, selectedCandidateId?: number) =>
    json<Result>(`/api/documents/${id}/results/${encodeURIComponent(fieldKey)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, selected_candidate_id: selectedCandidateId }),
    }),
};
