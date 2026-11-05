import { create } from 'zustand';

export interface Segment {
  id?: string;
  camera: string;
  start: number;
  end: number;
  confidence?: number;
  reason?: string;
  source?: 'manual' | 'suggested' | 'angle';
}

export interface CameraSync {
  source: string;
  file?: string;
  offset_s: number;
  offset_sec?: number;
  offset_ms?: number;
  offset_samples?: number;
  offset_frames?: number;
  drift_ppm?: number;
  drift_ms_per_hour?: number;
  link_confidence?: number;
  confidence?: number;
  psr?: number;
  window_offsets?: number[];
  window_std_ms?: number | null;
  state?: 'LOCKED' | 'VERIFY' | 'WEAK';
  warnings?: string[];
  duration_sec?: number;
  frame_rate?: number | null;
  waveform_index?: number;
  lane_locked?: boolean;
  is_master?: boolean;
}

export interface SyncCutProject {
  version: 1;
  fps: number;
  master_audio: string | null;
  master_camera: string | null;
  cameras: CameraSync[];
  program: Segment[];
  settings: { snapping: boolean; overlayCamera: string | null; playbackRate?: number };
  history: Array<{ cameras: CameraSync[]; program: Segment[] }>;
}

export type PipelineStage = 'idle' | 'uploading' | 'proxying' | 'syncing' | 'ai_cutting' | 'ready' | 'failed';
export type JobStatus = 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE' | 'REVOKED' | 'STALLED' | 'UNKNOWN' | 'CANCEL_REQUESTED';

export interface PipelineState {
  stage: PipelineStage;
  percentage: number | null;
  message: string;
  jobStatus: JobStatus | null;
}

export interface SyncReport {
  totalSyncSeconds: number;
  cameraCount: number;
  lockedCount: number;
  loopErrorMs: number;
  driftMsPerHour: number;
  suggestedCuts: number;
}

interface StudioState {
  sessionId: string;
  jobId: string | null;
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  playbackRate: number;
  syncData: CameraSync[];
  segments: Segment[];
  suggestedSegments: Segment[];
  fps: number;
  selectedCamera: string | null;
  masterCamera: string | null;
  projectHistory: Array<{ cameras: CameraSync[]; program: Segment[] }>;
  projectFuture: Array<{ cameras: CameraSync[]; program: Segment[] }>;
  manualOverrides: Record<number, string>;
  pipeline: PipelineState;
  files: File[];
  fileCount: number;
  allSources: string[];
  masterAudioUrl: string | null;
  syncStartedAt: number | null;
  syncReport: SyncReport | null;

  setCurrentTime: (t: number) => void;
  setDuration: (d: number) => void;
  setIsPlaying: (p: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  togglePlay: () => void;
  setSyncData: (d: CameraSync[]) => void;
  setSegments: (s: Segment[]) => void;
  setSuggestedSegments: (s: Segment[]) => void;
  applySuggestedSegments: () => void;
  setCameraOffset: (camera: string, offset: number) => void;
  setProgramCut: (camera: string, time: number) => void;
  editProgramSegments: (segments: Segment[]) => void;
  toggleCameraLaneLock: (camera: string) => void;
  splitProgramAtPlayhead: () => void;
  deleteProgramAtPlayhead: () => void;
  undoProjectEdit: () => void;
  redoProjectEdit: () => void;
  setSelectedCamera: (camera: string | null) => void;
  setSessionId: (id: string) => void;
  setFps: (fps: number) => void;
  toProjectFile: () => SyncCutProject;
  loadProjectFile: (project: SyncCutProject) => void;
  setOverride: (t: number, camera: string) => void;
  clearOverride: (t: number) => void;
  clearOverrides: () => void;
  setPipeline: (p: Partial<PipelineState>) => void;
  resetPipeline: () => void;
  setJobId: (id: string | null) => void;
  setFiles: (f: File[]) => void;
  setAllSources: (sources: string[]) => void;
  setMasterAudioUrl: (url: string | null) => void;
  setSyncStartedAt: (t: number | null) => void;
  setSyncReport: (r: SyncReport | null) => void;
  resetSession: () => void;
}

const INITIAL_PIPELINE: PipelineState = {
  stage: 'idle',
  percentage: 0,
  message: 'Drop camera clips to start auto sync.',
  jobStatus: null,
};

export const useStore = create<StudioState>((set, get) => ({
  sessionId: crypto.randomUUID(),
  jobId: null,
  currentTime: 0,
  duration: 0,
  isPlaying: false,
  playbackRate: 1,
  syncData: [],
  segments: [],
  suggestedSegments: [],
  fps: 25,
  selectedCamera: null,
  masterCamera: null,
  projectHistory: [],
  projectFuture: [],
  manualOverrides: {},
  pipeline: INITIAL_PIPELINE,
  files: [],
  fileCount: 0,
  allSources: [],
  masterAudioUrl: null,
  syncStartedAt: null,
  syncReport: null,

  setCurrentTime: (currentTime) => set({ currentTime }),
  setDuration: (duration) => set({ duration }),
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  setPlaybackRate: (playbackRate) => {
    if ([0.5, 1, 2].includes(playbackRate)) set({ playbackRate });
  },
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  setSyncData: (syncData) => set({
    syncData,
    masterCamera: syncData.find((camera) => camera.is_master)?.source ?? syncData[0]?.source ?? null,
  }),
  setSegments: (segments) => set({ segments }),
  setSuggestedSegments: (suggestedSegments) => set({ suggestedSegments }),
  applySuggestedSegments: () => {
    const state = get();
    if (!state.suggestedSegments.length) return;
    set({
      projectHistory: [...state.projectHistory, { cameras: state.syncData, program: state.segments }].slice(-100),
      projectFuture: [],
      segments: state.suggestedSegments.map((segment) => ({
        ...segment,
        source: 'suggested',
        id: segment.id ?? crypto.randomUUID(),
      })),
    });
  },
  setCameraOffset: (camera, offset) => set((state) => {
    const previous = state.syncData.find((item) => item.source === camera);
    if (!previous || previous.lane_locked || !Number.isFinite(offset)) return state;
    const delta = offset - previous.offset_s;
    if (Math.abs(delta) < 1e-6) return state;
    const snapshot = { cameras: state.syncData, program: state.segments };
    return {
      projectHistory: [...state.projectHistory, snapshot].slice(-100),
      projectFuture: [],
      syncData: state.syncData.map((item) => item.source !== camera ? item : {
        ...item, offset_s: offset, offset_sec: offset,
        offset_ms: offset * 1000, offset_samples: Math.round(offset * 16000), offset_frames: offset * state.fps,
      }),
      segments: state.segments.map((segment) => segment.camera === camera
        ? { ...segment, start: segment.start + delta, end: segment.end + delta }
        : segment),
    };
  }),
  setProgramCut: (camera, time) => set((state) => {
    const duration = state.duration;
    if (!camera || !Number.isFinite(time) || time < 0 || time >= duration) return state;
    const snapshot = { cameras: state.syncData, program: state.segments };
    const active = state.segments.find((segment) => time >= segment.start && time < segment.end);
    const before = state.segments.filter((segment) => segment.end <= time);
    if (active && time > active.start) before.push({ ...active, end: time });
    const nextBoundary = state.segments.filter((segment) => segment.start > time).reduce((nearest, segment) => Math.min(nearest, segment.start), duration);
    const end = active?.end ?? nextBoundary;
    const after = state.segments.filter((segment) => segment.start >= end);
    const next = [...before, { id: crypto.randomUUID(), camera, start: time, end, source: 'manual' as const, reason: 'Manual camera cut' }, ...after].sort((a, b) => a.start - b.start);
    return { projectHistory: [...state.projectHistory, snapshot].slice(-100), projectFuture: [], segments: next };
  }),
  editProgramSegments: (segments) => set((state) => ({
    projectHistory: [...state.projectHistory, { cameras: state.syncData, program: state.segments }].slice(-100),
    projectFuture: [],
    segments,
  })),
  toggleCameraLaneLock: (camera) => set((state) => ({
    projectHistory: [...state.projectHistory, { cameras: state.syncData, program: state.segments }].slice(-100),
    projectFuture: [],
    syncData: state.syncData.map((item) => item.source === camera ? { ...item, lane_locked: !item.lane_locked } : item),
  })),
  splitProgramAtPlayhead: () => set((state) => {
    const index = state.segments.findIndex((segment) => state.currentTime > segment.start + 0.1 && state.currentTime < segment.end - 0.1);
    if (index < 0) return state;
    const snapshot = { cameras: state.syncData, program: state.segments };
    const segment = state.segments[index];
    const next = [...state.segments];
    next.splice(index, 1, { ...segment, id: crypto.randomUUID(), end: state.currentTime }, { ...segment, id: crypto.randomUUID(), start: state.currentTime });
    return { projectHistory: [...state.projectHistory, snapshot].slice(-100), projectFuture: [], segments: next };
  }),
  deleteProgramAtPlayhead: () => set((state) => {
    const index = state.segments.findIndex((segment) => state.currentTime >= segment.start && state.currentTime < segment.end);
    if (index < 0) return state;
    const snapshot = { cameras: state.syncData, program: state.segments };
    const next = state.segments.filter((_, itemIndex) => itemIndex !== index);
    const removed = state.segments[index];
    if (index > 0) next[index - 1] = { ...next[index - 1], end: removed.end };
    else if (next.length) next[0] = { ...next[0], start: removed.start };
    return { projectHistory: [...state.projectHistory, snapshot].slice(-100), projectFuture: [], segments: next };
  }),
  undoProjectEdit: () => set((state) => {
    const previous = state.projectHistory[state.projectHistory.length - 1];
    if (!previous) return state;
    return {
      syncData: previous.cameras,
      segments: previous.program,
      projectHistory: state.projectHistory.slice(0, -1),
      projectFuture: [{ cameras: state.syncData, program: state.segments }, ...state.projectFuture].slice(0, 100),
    };
  }),
  redoProjectEdit: () => set((state) => {
    const next = state.projectFuture[0];
    if (!next) return state;
    return {
      syncData: next.cameras,
      segments: next.program,
      projectHistory: [...state.projectHistory, { cameras: state.syncData, program: state.segments }].slice(-100),
      projectFuture: state.projectFuture.slice(1),
    };
  }),
  setSelectedCamera: (selectedCamera) => set({ selectedCamera }),
  setSessionId: (sessionId) => set({ sessionId }),
  setFps: (fps) => set({ fps }),
  toProjectFile: () => {
    const state = get();
    return {
      version: 1, fps: state.fps, master_audio: state.masterAudioUrl,
      master_camera: state.masterCamera, cameras: state.syncData,
      program: state.segments, settings: { snapping: true, overlayCamera: null, playbackRate: state.playbackRate },
      history: state.projectHistory,
    };
  },
  loadProjectFile: (project) => set((state) => ({
    fps: project.fps,
    masterAudioUrl: project.master_audio,
    playbackRate: project.settings?.playbackRate ?? 1,
    masterCamera: project.master_camera,
    syncData: project.cameras,
    segments: project.program, // Ensure this is properly loaded
    suggestedSegments: [],
    projectHistory: project.history ?? [],
    projectFuture: [],
    pipeline: {
      ...state.pipeline,
      stage: project.program.length > 0 ? 'ready' : 'idle',
      percentage: project.program.length > 0 ? 100 : 0,
      message: project.program.length > 0 ? 'Saved project restored.' : 'Project restored. Add or generate a program timeline to continue.',
      jobStatus: project.program.length > 0 ? 'SUCCESS' : null,
    },
  })),
  setOverride: (t, camera) => set((s) => ({ manualOverrides: { ...s.manualOverrides, [t]: camera } })),
  clearOverride: (t) => set((s) => { const next = { ...s.manualOverrides }; delete next[t]; return { manualOverrides: next }; }),
  clearOverrides: () => set({ manualOverrides: {} }),
  setPipeline: (p) => set((s) => ({ pipeline: { ...s.pipeline, ...p } })),
  resetPipeline: () => set({ pipeline: INITIAL_PIPELINE }),
  setJobId: (jobId) => set({ jobId }),
  setFiles: (files) => set({ files, fileCount: files.length }),
  setAllSources: (sources) => {
    get().allSources.forEach((u) => u && URL.revokeObjectURL(u));
    set({ allSources: sources, fileCount: sources.length });
  },
  setMasterAudioUrl: (masterAudioUrl) => set({ masterAudioUrl }),
  setSyncStartedAt: (syncStartedAt) => set({ syncStartedAt }),
  setSyncReport: (syncReport) => set({ syncReport }),
  resetSession: () => set((s) => {
    s.allSources.forEach((u) => u && URL.revokeObjectURL(u));
    return {
      sessionId: crypto.randomUUID(), jobId: null, currentTime: 0, duration: 0, isPlaying: false,
      playbackRate: 1, syncData: [], segments: [], suggestedSegments: [], fps: 25,
      selectedCamera: null, masterCamera: null, projectHistory: [], projectFuture: [], manualOverrides: {},
      pipeline: INITIAL_PIPELINE, files: [], fileCount: 0, allSources: [], masterAudioUrl: null,
      syncStartedAt: null, syncReport: null,
    };
  }),
}));