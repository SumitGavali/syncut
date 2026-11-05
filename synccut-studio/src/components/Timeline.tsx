import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { restrictToHorizontalAxis } from '@dnd-kit/modifiers';
import {
  AudioLines,
  Magnet,
  MousePointer2,
  Scissors,
  Trash2,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Film,
} from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useEditorStore, type EditorClip } from '@/store/useEditorStore';
import TimelineClip from '@/components/TimelineClip';

type Tool = 'select' | 'blade';

const LABEL_WIDTH = 116;

function formatRulerTime(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const remaining = safe % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`;
}

function makeWaveformSvg() {
  const bars = Array.from({ length: 160 }, (_, index) => {
    const seed = Math.abs(Math.sin(index * 12.9898) * Math.cos(index * 4.1414));
    const height = 4 + seed * 31;
    return `<path d="M${index * 2 + 1} ${20 - height / 2}v${height}" stroke="#06b6d4" stroke-width="1.25" stroke-linecap="round"/>`;
  }).join('');
  return `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="320" height="40" viewBox="0 0 320 40">${bars}</svg>`)}")`;
}

const WAVEFORM_BACKGROUND = makeWaveformSvg();

interface TimelineProps {
  onCommitClips: (clips: EditorClip[]) => void;
}

export default function Timeline({ onCommitClips }: TimelineProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [zoom, setZoom] = useState<number | null>(null);
  const [tool, setTool] = useState<Tool>('select');

  const studioDuration = useStore((state) => state.duration);
  const clips = useEditorStore((state) => state.clips);
  const activeClipId = useEditorStore((state) => state.activeClipId);
  const playheadPosition = useEditorStore((state) => state.playheadPosition);
  const snapping = useEditorStore((state) => state.snapping);
  const setActiveClip = useEditorStore((state) => state.setActiveClip);
  const setPlayhead = useEditorStore((state) => state.setPlayhead);
  const moveClip = useEditorStore((state) => state.moveClip);
  const deleteClip = useEditorStore((state) => state.deleteClip);
  const splitClipAt = useEditorStore((state) => state.splitClipAt);
  const toggleSnapping = useEditorStore((state) => state.toggleSnapping);
  const undo = useEditorStore((state) => state.undo);
  const redo = useEditorStore((state) => state.redo);
  const undoStack = useEditorStore((state) => state.undoStack);
  const redoStack = useEditorStore((state) => state.redoStack);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const duration = Math.max(
    studioDuration,
    ...clips.map((clip) => clip.start + clip.duration),
    1,
  );
  const fitScale = viewportWidth > LABEL_WIDTH
    ? (viewportWidth - LABEL_WIDTH) / duration
    : 5;
  const pixelsPerSecond = zoom ?? fitScale;
  const timelineWidth = Math.max(viewportWidth, duration * pixelsPerSecond);
  const activeClip = clips.find((clip) => clip.id === activeClipId) ?? null;

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setViewportWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const timeAtClientX = useCallback((clientX: number) => {
    const node = viewportRef.current;
    if (!node) return 0;
    const bounds = node.getBoundingClientRect();
    const trackX = node.scrollLeft + clientX - bounds.left - LABEL_WIDTH;
    return Math.max(0, Math.min(duration, trackX / pixelsPerSecond));
  }, [duration, pixelsPerSecond]);

  const scrubPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('[data-timeline-interactive]')) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const position = timeAtClientX(event.clientX);
    if (tool === 'blade') {
      splitClipAt(position);
      onCommitClips(useEditorStore.getState().clips);
      return;
    }
    setPlayhead(position);
  };

  const scrubPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    setPlayhead(timeAtClientX(event.clientX));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    if (!event.active) return;
    const clip = useEditorStore.getState().clips.find((item) => item.id === String(event.active.id));
    if (!clip) return;
    const rawStart = Math.max(0, clip.start + event.delta.x / pixelsPerSecond);
    const start = snapping ? Math.round(rawStart * 2) / 2 : rawStart;
    moveClip(clip.id, start);
    onCommitClips(useEditorStore.getState().clips);
  };

  const handleDelete = () => {
    if (!activeClipId) return;
    deleteClip(activeClipId);
    onCommitClips(useEditorStore.getState().clips);
  };

  const handleSplit = () => {
    splitClipAt(playheadPosition);
    onCommitClips(useEditorStore.getState().clips);
  };

  const handleUndo = () => {
    undo();
    onCommitClips(useEditorStore.getState().clips);
  };

  const handleRedo = () => {
    redo();
    onCommitClips(useEditorStore.getState().clips);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement &&
        (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        event.shiftKey ? handleRedo() : handleUndo();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        handleRedo();
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        handleDelete();
      } else if (event.key.toLowerCase() === 's') {
        setTool('blade');
      } else if (event.key.toLowerCase() === 'v') {
        setTool('select');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeClipId, clips, playheadPosition, redo, undo, onCommitClips]);

  const tickStep = useMemo(() => {
    const candidates = [5, 10, 15, 30, 60, 120, 300, 600];
    return candidates.find((candidate) => candidate * pixelsPerSecond >= 100) ?? 600;
  }, [pixelsPerSecond]);
  const ticks = useMemo(() => {
    const count = Math.ceil(duration / tickStep);
    return Array.from({ length: count + 1 }, (_, index) => index * tickStep);
  }, [duration, tickStep]);
  const playheadX = LABEL_WIDTH + playheadPosition * pixelsPerSecond;
  const videoClips = clips.filter((clip) => clip.track === 0);

  return (
    <section
      data-tour="program-timeline"
      className="flex h-full min-h-0 flex-col overflow-hidden border-t border-border bg-background"
    >
      <header className="flex h-10 shrink-0 items-center gap-1 border-b border-border bg-panel px-3">
        <button
          type="button"
          title="Selection tool (V)"
          onClick={() => setTool('select')}
          className={`grid h-7 w-7 place-items-center rounded border ${tool === 'select' ? 'border-accent bg-accent/20 text-accent' : 'border-transparent text-gray-400 hover:bg-white/5 hover:text-gray-100'}`}
        >
          <MousePointer2 size={15} />
        </button>
        <button
          type="button"
          data-tour="blade-tool"
          title="Blade tool (S)"
          onClick={() => setTool('blade')}
          className={`grid h-7 w-7 place-items-center rounded border ${tool === 'blade' ? 'border-accent bg-accent/20 text-accent' : 'border-transparent text-gray-400 hover:bg-white/5 hover:text-gray-100'}`}
        >
          <Scissors size={15} />
        </button>
        <button type="button" title="Split at playhead" onClick={handleSplit} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5 hover:text-gray-100">
          <Scissors size={14} />
        </button>
        <button type="button" title="Delete selected clip" onClick={handleDelete} disabled={!activeClipId} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5 hover:text-rose-400 disabled:opacity-30">
          <Trash2 size={14} />
        </button>
        <span className="mx-1 h-4 w-px bg-[#333]" />
        <button type="button" title="Undo" onClick={handleUndo} disabled={!undoStack.length} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5 disabled:opacity-30">
          <Undo2 size={15} />
        </button>
        <button type="button" title="Redo" onClick={handleRedo} disabled={!redoStack.length} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5 disabled:opacity-30">
          <Redo2 size={15} />
        </button>
        <button
          type="button"
          aria-pressed={snapping}
          title="Toggle snapping"
          onClick={toggleSnapping}
          className={`ml-2 flex h-7 items-center gap-1.5 rounded border px-2 text-[10px] ${snapping ? 'border-accent bg-accent/15 text-accent' : 'border-transparent text-gray-500 hover:bg-white/5'}`}
        >
          <Magnet size={13} /> Snap {snapping ? 'On' : 'Off'}
        </button>
        <div className="ml-auto flex items-center gap-1.5">
          <button type="button" aria-label="Zoom out" onClick={() => setZoom(Math.max(0.25, pixelsPerSecond / 1.25))} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5">
            <ZoomOut size={15} />
          </button>
          <input
            aria-label="Timeline zoom"
            type="range"
            min="0.25"
            max="90"
            step="0.25"
            value={pixelsPerSecond}
            onChange={(event) => setZoom(Number(event.currentTarget.value))}
            className="w-24 accent-[#06b6d4]"
          />
          <button type="button" aria-label="Zoom in" onClick={() => setZoom(Math.min(90, pixelsPerSecond * 1.25))} className="grid h-7 w-7 place-items-center rounded text-gray-400 hover:bg-white/5">
            <ZoomIn size={15} />
          </button>
          <button type="button" onClick={() => setZoom(null)} className="rounded border border-border px-2 py-1 text-[10px] text-gray-300 hover:border-accent">
            Fit
          </button>
        </div>
      </header>

      <DndContext
        sensors={sensors}
        modifiers={[restrictToHorizontalAxis]}
        onDragEnd={handleDragEnd}
      >
        <div
          ref={viewportRef}
          data-tour="timeline-trimming"
          className={`relative min-h-0 flex-1 overflow-auto bg-background ${tool === 'blade' ? 'cursor-crosshair' : 'cursor-default'}`}
          onPointerDown={scrubPointerDown}
          onPointerMove={scrubPointerMove}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
        >
          <div className="relative min-h-full" style={{ width: LABEL_WIDTH + timelineWidth, minWidth: '100%' }}>
            <div className="sticky top-0 z-30 flex h-8 border-b border-border bg-panel">
              <div className="sticky left-0 z-40 flex shrink-0 items-center border-r border-border bg-panel px-3 text-[9px] font-semibold uppercase tracking-wide text-gray-500" style={{ width: LABEL_WIDTH }}>
                Timecode
              </div>
              <div className="relative h-full" style={{ width: timelineWidth }}>
                {ticks.map((tick) => (
                  <div key={tick} className="absolute inset-y-0 border-l border-white/[0.07]" style={{ left: tick * pixelsPerSecond }}>
                    <span className="absolute left-1 top-1 whitespace-nowrap font-mono text-[9px] text-gray-500">
                      {formatRulerTime(tick)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex h-[76px] border-b border-border">
              <div className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-border bg-panel px-3" style={{ width: LABEL_WIDTH }}>
                <Film size={14} className="text-accent" />
                <span className="text-[10px] font-bold text-gray-300">V1</span>
                <span className="truncate text-[10px] text-gray-500">Program</span>
              </div>
              <div data-tour="program-track" className="relative h-full bg-background" style={{ width: timelineWidth }}>
                {videoClips.map((clip) => (
                  <TimelineClip
                    key={clip.id}
                    clip={clip}
                    pixelsPerSecond={pixelsPerSecond}
                    isActive={clip.id === activeClipId}
                    onCameraOverride={onCommitClips}
                  />
                ))}
                {!videoClips.length && (
                  <div className="absolute inset-0 flex items-center px-4 text-[10px] text-gray-600">
                    Add media and run sync to create the program sequence.
                  </div>
                )}
              </div>
            </div>

            <div className="flex h-[52px] border-b border-border">
              <div className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-border bg-panel px-3" style={{ width: LABEL_WIDTH }}>
                <AudioLines size={14} className="text-accent" />
                <span className="text-[10px] font-bold text-gray-300">A1</span>
                <span className="text-[10px] text-gray-500">Audio</span>
              </div>
              <div className="relative h-full overflow-hidden bg-panel" style={{ width: timelineWidth }}>
                <div
                  aria-label="Audio waveform"
                  className="absolute inset-x-0 top-1.5 bottom-1.5 rounded-sm border-y border-accent/40 opacity-75"
                  style={{
                    backgroundImage: WAVEFORM_BACKGROUND,
                    backgroundRepeat: 'repeat-x',
                    backgroundSize: `${Math.max(80, 320 * pixelsPerSecond / 8)}px 100%`,
                    backgroundPosition: 'center',
                  }}
                />
              </div>
            </div>

            <div
              aria-hidden="true"
              className="pointer-events-none absolute bottom-0 top-8 z-30 w-px border-l border-accent shadow-[0_0_8px_#06b6d4]"
              style={{ left: playheadX }}
            >
              <div className="absolute -left-[5px] -top-[5px] h-3 w-3 rotate-45 rounded-sm bg-accent" />
              <span className="absolute -left-7 top-1 whitespace-nowrap rounded border border-accent bg-background px-1.5 py-0.5 font-mono text-[9px] font-bold text-accent">
                {formatRulerTime(playheadPosition)}
              </span>
            </div>
          </div>
        </div>
      </DndContext>
    </section>
  );
}
