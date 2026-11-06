import axios from 'axios';
import type { Segment, SyncCutProject } from '@/store/useStore';
import type { Project, ProjectStatus } from '@/store/useProjectStore';
import type { EditorClip } from '@/store/useEditorStore'; // <-- IMPORT ADDED

const http = axios.create({ baseURL: import.meta.env.VITE_API_BASE ?? '' });

// Attach Authorization Bearer token automatically if logged in
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('synccut_auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** POST /api/upload (multipart: session_id, files) -> { job_id } */
export async function uploadFiles(sessionId: string, files: File[], onProgress?: (pct: number) => void) {
  const fd = new FormData();
  fd.append('session_id', sessionId);
  files.forEach((f) => fd.append('files', f));
  const { data } = await http.post<{ job_id: string }>('/api/upload', fd, {
    onUploadProgress: (e) => e.total && onProgress?.(Math.round((e.loaded / e.total) * 100)),
  });
  return data.job_id;
}

/** POST /api/sync_async (form-data: session_id, reference, inputs) -> { job_id } */
export async function startSync(sessionId: string, reference: string, inputs: string[]) {
  const fd = new FormData();
  fd.append('session_id', sessionId);
  fd.append('reference', reference);
  inputs.forEach((i) => fd.append('inputs', i));
  const { data } = await http.post<{ job_id: string }>('/api/sync_async', fd);
  return data.job_id;
}

export interface JobStatusResponse {
  status: 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED' | 'STALLED' | 'UNKNOWN';
  progress: number | null;
  metadata?: Record<string, any>;
  result?: any;
  error?: string;
}

/** GET /api/job/status?job_id= */
export async function getJobStatus(jobId: string) {
  const { data } = await http.get<Omit<JobStatusResponse, 'progress'>>('/api/job/status', {
    params: { job_id: jobId },
  });
  const current = data.metadata?.current;
  const total = data.metadata?.total;
  const progress = typeof current === 'number' && typeof total === 'number' && total > 0
    ? Math.min(100, Math.max(0, (current / total) * 100))
    : null;
  return { ...data, progress } as JobStatusResponse;
}

/** POST /api/job/cancel */
export async function cancelJob(jobId: string) {
  const { data } = await http.post<{ job_id: string; status: string }>('/api/job/cancel', { job_id: jobId });
  return data;
}

export async function getCameraWaveform(sessionId: string, index: number) {
  const { data } = await http.get<ArrayBuffer>(
    `/api/session/${encodeURIComponent(sessionId)}/waveform/${index}`,
    { responseType: 'arraybuffer' },
  );
  return new Uint8Array(data);
}

const thumbnailCache = new Map<string, Promise<string>>();

export async function getCameraThumbnail(sessionId: string, index: number, time: number) {
  const bucket = Math.max(0, Math.round(time / 10) * 10);
  const key = `${sessionId}:${index}:${bucket}`;
  const existing = thumbnailCache.get(key);
  if (existing) return existing;

  const pending = http.get<Blob>(
    `/api/session/${encodeURIComponent(sessionId)}/thumbnail/${index}`,
    { params: { time: bucket }, responseType: 'blob' },
  ).then(({ data }) => URL.createObjectURL(data));
  thumbnailCache.set(key, pending);
  try {
    const url = await pending;
    while (thumbnailCache.size > 200) {
      const oldest = thumbnailCache.keys().next().value;
      if (!oldest) break;
      const oldValue = thumbnailCache.get(oldest);
      thumbnailCache.delete(oldest);
      oldValue?.then((oldUrl) => URL.revokeObjectURL(oldUrl)).catch(() => undefined);
    }
    return url;
  } catch (error) {
    thumbnailCache.delete(key);
    throw error;
  }
}

export function getSessionMediaUrl(sessionId: string, index: number) {
  const base = import.meta.env.VITE_API_BASE ?? '';
  const token = localStorage.getItem('synccut_auth_token');
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${base}/api/session/${encodeURIComponent(sessionId)}/media/${index}${tokenParam}`;
}

export async function loadSessionProject(sessionId: string) {
  const { data } = await http.get<{ project: SyncCutProject }>(
    `/api/session/${encodeURIComponent(sessionId)}/project`,
  );
  return data.project;
}

export async function saveSessionProject(sessionId: string, project: SyncCutProject) {
  await http.put(`/api/session/${encodeURIComponent(sessionId)}/project`, project);
}

/** POST /api/switches (JSON: session_id) -> { segments } */
export async function runRoughCut(sessionId: string) {
  const { data } = await http.post<{ segments: Segment[] }>('/api/switches', { session_id: sessionId });
  return data.segments;
}

/** POST /api/export/timeline (JSON: session_id, format, project, overrides, timeline_clips) -> blob */
export async function exportTimeline(
  sessionId: string,
  format: string,
  project: SyncCutProject,
  overrides: Record<number, string>,
  timelineClips: EditorClip[], // <-- NEW ARGUMENT ADDED
) {
  const res = await http.post(
    '/api/export/timeline',
    {
      session_id: sessionId,
      format,
      project,
      overrides,
      timeline_clips: timelineClips // <-- NEW PAYLOAD ADDED
    },
    { responseType: 'blob' },
  );
  const cd: string | undefined = res.headers['content-disposition'];
  const name = cd?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)?.[1];
  return { blob: res.data as Blob, filename: name ? decodeURIComponent(name) : null };
}

// -------------------------------------------------------------------------
// AUTH & PROJECT API CLIENT
// -------------------------------------------------------------------------

export async function loginApi(email: string, password?: string) {
  const { data } = await http.post<{ user: any; token: string }>('/api/auth/login', { email, password });
  return data;
}

export async function registerApi(email: string, password: string, name?: string) {
  const { data } = await http.post<{ user: any; token: string }>('/api/auth/register', { email, password, name });
  return data;
}

export async function getMeApi() {
  const { data } = await http.get<{ user: any }>('/api/auth/me');
  return data.user;
}

export interface BillingSubscription {
  tier: 'free' | 'pro' | 'studio';
  expires_at: string | null;
}

export async function getBillingSubscriptionApi(): Promise<BillingSubscription> {
  const { data } = await http.get<BillingSubscription>('/api/billing/subscription');
  return data;
}

export async function createCheckoutApi(): Promise<string> {
  const { data } = await http.post<{ checkout_url: string }>('/api/billing/checkout');
  return data.checkout_url;
}

export async function logoutApi() {
  await http.post('/api/auth/logout');
}

export async function getProjectsApi() {
  const { data } = await http.get<{ projects: Project[] }>('/api/projects');
  return data.projects;
}

export async function createProjectApi(project: Partial<Project>) {
  const { data } = await http.post<{ project: Project }>('/api/projects', project);
  return data.project;
}

export async function deleteProjectApi(projectId: string) {
  const { data } = await http.delete<{ success: boolean }>(`/api/projects/${projectId}`);
  return data.success;
}

export async function updateProjectApi(projectId: string, updates: { status?: ProjectStatus; name?: string }) {
  const { data } = await http.patch<{ success: boolean }>(`/api/projects/${projectId}`, updates);
  return data.success;
}

export interface StorageInfo {
  drive: string;
  path: string;
  free_gb: number;
  total_gb: number;
  used_gb: number;
  is_sufficient: boolean;
}

export async function getStorageInfoApi(): Promise<StorageInfo> {
  const { data } = await http.get<StorageInfo>('/api/system/storage');
  return data;
}