import type {
  BatchDetail,
  BatchSummary,
  FileInfo,
  HistoryEntry,
  Meta,
  Preview,
  ProcessResult,
  Profile,
  RecordDetail,
  RecordSummary,
  Role,
  Sample,
  SampleLoadResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, "Cannot reach the local server. Check that the backend is running on 127.0.0.1:8000.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : `Request failed (${res.status}).`);
  }
  return data as T;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  meta: () => request<Meta>("GET", "/api/meta"),
  samples: () => request<Sample[]>("GET", "/api/samples"),
  loadSample: (id: string) => request<SampleLoadResult>("POST", `/api/samples/${encodeURIComponent(id)}/load`),
  batches: () => request<BatchSummary[]>("GET", "/api/batches"),
  createBatch: (name: string, template_id: string) => request<BatchDetail>("POST", "/api/batches", { name, template_id }),
  batch: (id: number) => request<BatchDetail>("GET", `/api/batches/${id}`),
  deleteBatch: (id: number) => request<void>("DELETE", `/api/batches/${id}`),
  upload: (batchId: number, role: Role, files: File[]) => {
    const form = new FormData();
    form.set("role", role);
    for (const f of files) form.append("files", f, f.name);
    return request<FileInfo[]>("POST", `/api/batches/${batchId}/files`, form);
  },
  process: (batchId: number) => request<ProcessResult>("POST", `/api/batches/${batchId}/process`),
  records: (batchId: number, filters: Record<string, string | boolean | undefined>) =>
    request<RecordSummary[]>("GET", `/api/batches/${batchId}/records${qs(filters)}`),
  history: (batchId: number) => request<HistoryEntry[]>("GET", `/api/batches/${batchId}/history`),
  exportUrl: (batchId: number) => `/api/batches/${batchId}/export`,
  preview: (fileId: number, sheet?: string | null, headerRow?: number | null, dateColumn?: string | null) =>
    request<Preview>("GET", `/api/files/${fileId}/preview${qs({ sheet, header_row: headerRow, date_column: dateColumn })}`),
  confirmMapping: (
    fileId: number,
    body: {
      sheet: string | null;
      header_row: number | null;
      mapping: Record<string, string | null>;
      date_order: string;
      default_currency: string | null;
      profile_name: string | null;
    },
  ) => request<FileInfo>("POST", `/api/files/${fileId}/mapping`, body),
  removeFile: (fileId: number) => request<void>("DELETE", `/api/files/${fileId}`),
  fileContentUrl: (fileId: number) => `/api/files/${fileId}/content`,
  profiles: () => request<Profile[]>("GET", "/api/mapping-profiles"),
  record: (id: number) => request<RecordDetail>("GET", `/api/records/${id}`),
  correct: (id: number, values: Record<string, string | null>, note: string | null) =>
    request<{ record: RecordDetail; changed_fields: string[]; summary: { approvals_withdrawn: number[] } }>(
      "POST",
      `/api/records/${id}/corrections`,
      { values, note },
    ),
  approve: (id: number, note: string | null) => request<RecordDetail>("POST", `/api/records/${id}/approve`, { note }),
  exclude: (id: number, reason: string) => request<RecordDetail>("POST", `/api/records/${id}/exclude`, { reason }),
  reopen: (id: number, note: string | null) => request<RecordDetail>("POST", `/api/records/${id}/reopen`, { note }),
  note: (id: number, note: string) => request<RecordDetail>("POST", `/api/records/${id}/notes`, { note }),
  link: (id: number, reference_id: number, note: string | null) =>
    request<RecordDetail>("POST", `/api/records/${id}/link`, { reference_id, note }),
  unlink: (id: number) => request<RecordDetail>("DELETE", `/api/records/${id}/link`),
};
