import { create } from 'zustand';

export interface EditorClip {
  id: string;
  name: string;
  track: number;
  start: number;
  duration: number;
  color: string;
  confidence?: number;
  sourceIndex?: number;
  sourceUrl?: string;
  reason?: string;
  scale: number;
  positionX: number;
  positionY: number;
  rotation: number;
  opacity: number;
}

interface EditorSnapshot {
  clips: EditorClip[];
  activeClipId: string | null;
}

interface EditorState {
  activeClipId: string | null;
  playheadPosition: number;
  isPlaying: boolean;
  clips: EditorClip[];
  selectedSourceIndex: number | null;
  snapping: boolean;
  undoStack: EditorSnapshot[];
  redoStack: EditorSnapshot[];
  setActiveClip: (id: string | null) => void;
  setPlayhead: (position: number) => void;
  togglePlay: () => void;
  setIsPlaying: (playing: boolean) => void;
  setClips: (clips: EditorClip[]) => void;
  moveClip: (id: string, start: number) => void;
  deleteClip: (id: string) => void;
  splitClipAt: (position: number) => void;
  setClipCamera: (id: string, camera: string, sourceIndex?: number, sourceUrl?: string) => void;
  setClipTransform: (id: string, key: 'scale' | 'positionX' | 'positionY' | 'rotation' | 'opacity', value: number) => void;
  setSelectedSourceIndex: (index: number | null) => void;
  toggleSnapping: () => void;
  undo: () => void;
  redo: () => void;
}

const EMPTY_SNAPSHOT: EditorSnapshot = { clips: [], activeClipId: null };
const MAX_HISTORY = 100;

function snapshot(state: EditorState): EditorSnapshot {
  return { clips: state.clips, activeClipId: state.activeClipId };
}

function withHistory(state: EditorState, update: Partial<EditorState>): Partial<EditorState> {
  return {
    ...update,
    undoStack: [...state.undoStack, snapshot(state)].slice(-MAX_HISTORY),
    redoStack: [],
  };
}

export const useEditorStore = create<EditorState>((set) => ({
  activeClipId: null,
  playheadPosition: 0,
  isPlaying: false,
  clips: [],
  selectedSourceIndex: null,
  snapping: true,
  undoStack: [],
  redoStack: [],

  setActiveClip: (activeClipId) => set({ activeClipId }),
  setPlayhead: (playheadPosition) => set({
    playheadPosition: Number.isFinite(playheadPosition) ? Math.max(0, playheadPosition) : 0,
  }),
  togglePlay: () => set((state) => ({ isPlaying: !state.isPlaying })),
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  setClips: (clips) => set((state) => {
    const activeClipId = clips.some((clip) => clip.id === state.activeClipId)
      ? state.activeClipId
      : clips[0]?.id ?? null;
    return { clips, activeClipId };
  }),
  moveClip: (id, start) => set((state) => {
    if (!Number.isFinite(start)) return state;
    const clips = state.clips.map((clip) => clip.id === id
      ? { ...clip, start: Math.max(0, start) }
      : clip);
    if (clips.every((clip, index) => clip === state.clips[index])) return state;
    return withHistory(state, { clips });
  }),
  deleteClip: (id) => set((state) => {
    const clips = state.clips.filter((clip) => clip.id !== id);
    if (clips.length === state.clips.length) return state;
    const activeClipId = state.activeClipId === id ? clips[0]?.id ?? null : state.activeClipId;
    return withHistory(state, { clips, activeClipId });
  }),
  splitClipAt: (position) => set((state) => {
    const index = state.clips.findIndex((clip) =>
      position > clip.start + 0.05 && position < clip.start + clip.duration - 0.05,
    );
    if (index < 0) return state;
    const original = state.clips[index];
    const leftDuration = position - original.start;
    const right: EditorClip = {
      ...original,
      id: crypto.randomUUID(),
      start: position,
      duration: original.duration - leftDuration,
    };
    const clips = [...state.clips];
    clips.splice(index, 1,
      { ...original, id: crypto.randomUUID(), duration: leftDuration },
      right,
    );
    return withHistory(state, { clips, activeClipId: right.id });
  }),
  setClipCamera: (id, name, sourceIndex, sourceUrl) => set((state) => {
    const clips = state.clips.map((clip) => clip.id === id
      ? { ...clip, name, sourceIndex, sourceUrl }
      : clip);
    return withHistory(state, { clips });
  }),
  setClipTransform: (id, key, value) => set((state) => {
    if (!Number.isFinite(value)) return state;
    const clips = state.clips.map((clip) => clip.id === id
      ? { ...clip, [key]: value }
      : clip);
    return { clips };
  }),
  setSelectedSourceIndex: (selectedSourceIndex) => set({ selectedSourceIndex }),
  toggleSnapping: () => set((state) => ({ snapping: !state.snapping })),
  undo: () => set((state) => {
    const previous = state.undoStack[state.undoStack.length - 1];
    if (!previous) return state;
    return {
      ...previous,
      undoStack: state.undoStack.slice(0, -1),
      redoStack: [snapshot(state), ...state.redoStack].slice(0, MAX_HISTORY),
    };
  }),
  redo: () => set((state) => {
    const next = state.redoStack[0];
    if (!next) return state;
    return {
      ...next,
      undoStack: [...state.undoStack, snapshot(state)].slice(-MAX_HISTORY),
      redoStack: state.redoStack.slice(1),
    };
  }),
}));

export { EMPTY_SNAPSHOT };
