export type Draft = {
  id: string;
  status: string;
  filename: string;
  file_size: number;
  mime_type?: string | null;
  title: string;
  description: string;
  tags: string[];
  hashtags: string[];
  seo_keywords: string[];
  category_id: string;
  playlist_id: string | null;
  privacy_status: "private" | "unlisted" | "public";
  scheduled_at: string | null;
  metadata_source: string;
  manually_edited: boolean;
  youtube_video_id: string | null;
  youtube_url: string | null;
  created_at: string;
  updated_at?: string;
  transcript?: { text: string; status: string; provider: string; error?: string } | null;
  thumbnails?: { id: string; source: string; selected: boolean; url: string; upload_status: string; error?: string }[];
};

export type Job = {
  id: string;
  draft_id: string;
  status: string;
  progress: number;
  retry_count: number;
  max_retries?: number;
  run_at: string;
  last_error?: string;
  youtube_video_id?: string | null;
  processing_status?: string | null;
  verification_attempts?: number;
  updated_at?: string;
  logs?: Array<{ level: string; event: string; message: string; created_at: string }>;
};

export type Dashboard = {
  drafts: Draft[];
  jobs: Job[];
  auth: { authenticated: boolean; channel: { id: string; title: string; thumbnail?: string } | null };
  checks: Record<string, boolean>;
  server_time: string;
};

export type Playlist = { id: string; title: string; description: string; privacy_status: string; video_count: number };
export type Category = { id: string; title: string };

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (configuredApiUrl || (import.meta.env.DEV ? "http://localhost:5000/api" : "/api")).replace(/\/$/, "");
const ABSOLUTE_URL = /^https?:\/\//i.test(API_URL);

const configurationError = import.meta.env.PROD && ABSOLUTE_URL && /localhost|127\.0\.0\.1|0\.0\.0\.0/i.test(API_URL)
  ? "The production frontend points to a local API address. Use the same-origin /api default or configure the public HTTPS API URL."
  : "";

export class ApiFailure extends Error {
  code: string;
  status: number;
  constructor(message: string, code = "request_failed", status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

type CallOptions = RequestInit & { timeoutMs?: number };

async function call<T>(path: string, options: CallOptions = {}): Promise<T> {
  if (configurationError) throw new ApiFailure(configurationError, "api_configuration_error");
  const { timeoutMs = options.body instanceof FormData ? 30 * 60_000 : 30_000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...fetchOptions,
      credentials: "include",
      signal: controller.signal,
      headers: { Accept: "application/json", ...fetchOptions.headers },
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiFailure(
      aborted ? "The backend request timed out" : `Cannot connect to the backend at ${API_URL}`,
      aborted ? "request_timeout" : "backend_unreachable",
    );
  } finally {
    window.clearTimeout(timer);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiFailure(body.error?.message || `Request failed (${response.status})`, body.error?.code, response.status);
  }
  return body;
}

function json(method: string, value?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: value === undefined ? undefined : JSON.stringify(value),
  };
}

export const api = {
  url: API_URL,
  operatorStatus: () => call<{ required: boolean; authenticated: boolean; local_bypass: boolean }>("/operator/status"),
  operatorLogin: (password: string) => call<{ authenticated: boolean }>("/operator/login", json("POST", { password })),
  operatorLogout: () => call<{ authenticated: boolean }>("/operator/logout", json("POST")),
  dashboard: (limit = 100) => call<Dashboard>(`/dashboard?limit=${limit}`),
  auth: () => call<Dashboard["auth"]>("/auth/status"),
  login: () => call<{ auth_url: string }>("/auth/login"),
  logout: () => call("/auth/logout", json("POST")),
  settings: () => call<{ status: string; checks: Record<string, boolean> }>("/settings"),
  drafts: () => call<{ drafts: Draft[] }>("/drafts"),
  draft: (id: string) => call<{ draft: Draft }>(`/drafts/${id}`),
  createDraft: (file: File) => {
    const data = new FormData();
    data.append("video", file);
    return call<{ draft: Draft }>("/drafts", { method: "POST", body: data });
  },
  updateDraft: (id: string, value: Partial<Draft>) => call<{ draft: Draft }>(`/drafts/${id}`, json("PATCH", value)),
  generateMetadata: (id: string) => call<{ draft: Draft }>(`/drafts/${id}/metadata/generate`, {
    ...json("POST", {}), timeoutMs: 90_000,
  }),
  generateTranscript: (id: string) => call(`/drafts/${id}/transcript/generate`, {
    method: "POST", timeoutMs: 30 * 60_000,
  }),
  saveTranscript: (id: string, text: string) => call(`/drafts/${id}/transcript`, json("PUT", { text })),
  generateThumbnails: (id: string) => call(`/drafts/${id}/thumbnails/generate`, { method: "POST" }),
  uploadThumbnail: (id: string, file: File) => {
    const data = new FormData();
    data.append("thumbnail", file);
    return call(`/drafts/${id}/thumbnails`, { method: "POST", body: data });
  },
  selectThumbnail: (draftId: string, thumbnailId: string) => call(`/drafts/${draftId}/thumbnails/${thumbnailId}/select`, { method: "POST" }),
  playlists: () => call<{ playlists: Playlist[] }>("/playlists"),
  categories: (region = "NL") => call<{ categories: Category[] }>(`/playlists/categories?region=${encodeURIComponent(region)}`),
  jobs: () => call<{ jobs: Job[] }>("/jobs"),
  job: (id: string) => call<{ job: Job }>(`/jobs/${id}`),
  createJob: (id: string, runAt?: string) => call<{ job: Job }>(`/drafts/${id}/jobs`, {
    ...json("POST", { run_at: runAt || null }),
    headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
  }),
  batch: (draftIds: string[]) => call("/batch-jobs", json("POST", { draft_ids: draftIds })),
  retry: (id: string) => call(`/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: string) => call(`/jobs/${id}/cancel`, { method: "POST" }),
  assetUrl: (path: string) => {
    const apiBase = ABSOLUTE_URL ? API_URL.replace(/\/api$/, "") : "";
    return `${apiBase}${path}`;
  },
};
