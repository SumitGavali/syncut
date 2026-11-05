import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { Redo2, Scissors, Trash2, Undo2, ZoomIn, ZoomOut, Wand2 } from 'lucide-react';
import { getCameraThumbnail } from '@/lib/api';
import { useStore } from '@/store/useStore';
import type { Segment } from '@/store/useStore';

const CAMERA_COLORS = ['#00E5FF', '#34d399', '#a78bfa', '#f59e0b', '#f87171', '#38bdf8', '#fb923c', '#e879f9'];

function formatTimecode(time: number, fps: number) {
  const rate = Math.max(1, Math.round(fps));
  const frames = Math.round(Math.abs(time) * rate);
  const frame = frames % rate;
  const totalSeconds = Math.floor(frames / rate);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return `${time < 0 ? '-' : ''}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}:${String(frame).padStart(2, '0')}`;
}

function tickInterval(pxPerSecond: number) {
  const raw = 88 / pxPerSecond;
  const power = 10 ** Math.floor(Math.log10(Math.max(raw, 0.001)));
  return [1, 2, 5, 10].map((factor) => factor * power).find((step) => step >= raw) ?? raw;
}

// ─────────────────────────────────────────────
// Filmstrip Component (Background thumbnails)
// ─────────────────────────────────────────────
function SegmentFilmstrip({
  sessionId,
  cameraIndex,
  segment,
  cameraOffset,
  sourceDuration,
  timelineStart,
  pxPerSecond,
  scrollLeft,
  viewportWidth,
}: {
  sessionId: string;
  cameraIndex: number;
  segment: Segment;
  cameraOffset: number;
  sourceDuration: number;
  timelineStart: number;
  pxPerSecond: number;
  scrollLeft: number;
  viewportWidth: number;
}) {
  const [frames, setFrames] = useState<Record<number, string>>({});
  const visibleStart = timelineStart + scrollLeft / pxPerSecond;
  const visibleEnd = visibleStart + viewportWidth / pxPerSecond;
  const localStart = Math.max(0, Math.max(segment.start, visibleStart) - cameraOffset);
  const localEnd = Math.min(sourceDuration, Math.min(segment.end, visibleEnd) - cameraOffset);

  const thumbnailTimes = useMemo(() => {
    if (localEnd < localStart) return [];
    const first = Math.floor(localStart / 10) * 10;
    const times: number[] = [];
    for (let time = first; time <= localEnd; time += 10) times.push(time);
    return times;
  }, [localEnd, localStart]);

  const requestKey = thumbnailTimes.join(',');

  useEffect(() => {
    let active = true;
    void Promise.all(thumbnailTimes.map(async (time) => {
      try {
        const url = await getCameraThumbnail(sessionId, cameraIndex, time);
        if (active) setFrames((current) => ({ ...current, [time]: url }));
      } catch {
        // Audio-only sources and unsupported video streams have no filmstrip.
      }
    }));
    return () => { active = false; };
  }, [sessionId, cameraIndex, requestKey]);

  return (
    <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden flex">
      {thumbnailTimes.map((time) => frames[time] && (
        <img
          key={time}
          src={frames[time]}
          alt=""
          draggable={false}
          className="absolute inset-y-0 h-full object-cover opacity-60 mix-blend-screen"
          style={{
            left: (cameraOffset + time - segment.start) * pxPerSecond,
            width: 10 * pxPerSecond,
          }}
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────
// Drag State Interface
// ─────────────────────────────────────────────
interface ProgramDrag {
  pointerId: number;
  index: number;
  mode: 'move' | 'left' | 'right';
  startX: number;
  original: Segment[];
  moved: boolean;
}

// ─────────────────────────────────────────────
// Main Timeline Component
// ─────────────────────────────────────────────
export default function WaveformTimeline() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const programDrag = useRef<ProgramDrag | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [zoom, setZoom] = useState<number | null>(null);
  const [programPreview, setProgramPreview] = useState<Segment[] | null>(null);

  const sessionId = useStore((state) => state.sessionId);
  const cameras = useStore((state) => state.syncData);
  const segments = useStore((state) => state.segments);
  const suggestions = useStore((state) => state.suggestedSegments);
  const duration = useStore((state) => state.duration);
  const currentTime = useStore((state) => state.currentTime);
  const fps = useStore((state) => state.fps);
  const selectedCamera = useStore((state) => state.selectedCamera);
  const setCurrentTime = useStore((state) => state.setCurrentTime);
  const setCameraOffset = useStore((state) => state.setCameraOffset);
  const setProgramCut = useStore((state) => state.setProgramCut);
  const editProgramSegments = useStore((state) => state.editProgramSegments);
  const splitProgramAtPlayhead = useStore((state) => state.splitProgramAtPlayhead);
  const deleteProgramAtPlayhead = useStore((state) => state.deleteProgramAtPlayhead);
  const applySuggestedSegments = useStore((state) => state.applySuggestedSegments);
  const undoProjectEdit = useStore((state) => state.undoProjectEdit);
  const redoProjectEdit = useStore((state) => state.redoProjectEdit);
  const projectHistory = useStore((state) => state.projectHistory);
  const projectFuture = useStore((state) => state.projectFuture);

  const timelineStart = 0;
  const timelineEnd = Math.max(1, duration, ...segments.map((segment) => segment.end));
  const rangeDuration = Math.max(1, timelineEnd - timelineStart);

  // Fit logic
  const fitZoom = viewportWidth > 0 ? Math.max(0.001, viewportWidth / (rangeDuration * 12)) : 1;
  const effectiveZoom = zoom ?? fitZoom;
  const pxPerSecond = 12 * effectiveZoom;
  const contentWidth = Math.max(viewportWidth, rangeDuration * pxPerSecond);
  const activeSegments = programPreview ?? segments;

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setViewportWidth(Math.max(0, entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const timeAtClientX = useCallback((clientX: number) => {
    const viewport = viewportRef.current;
    if (!viewport) return 0;
    const rect = viewport.getBoundingClientRect();
    return timelineStart + (viewport.scrollLeft + clientX - rect.left) / pxPerSecond;
  }, [pxPerSecond]);

  const scrubPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('[data-interactive]')) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setCurrentTime(Math.min(duration, Math.max(0, timeAtClientX(event.clientX))));
  };

  const scrubPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    setCurrentTime(Math.min(duration, Math.max(0, timeAtClientX(event.clientX))));
  };

  const beginProgramDrag = (index: number, event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    // If within 8px of edge, trigger trim mode
    const mode: ProgramDrag['mode'] = localX < 8 ? 'left' : rect.width - localX < 8 ? 'right' : 'move';

    programDrag.current = {
      pointerId: event.pointerId,
      index,
      mode,
      startX: event.clientX,
      original: segments.map((segment) => ({ ...segment })),
      moved: false,
    };
  };

  const moveProgramDrag = (event: PointerEvent<HTMLDivElement>) => {
    const drag = programDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const original = drag.original.map((segment) => ({ ...segment }));
    const segment = original[drag.index];
    if (!segment) return;
    const delta = (event.clientX - drag.startX) / pxPerSecond;
    if (Math.abs(delta) > 0.01) drag.moved = true;
    if (!drag.moved) return;

    if (drag.mode === 'left') {
      const lower = drag.index > 0 ? original[drag.index - 1].start + 0.25 : 0;
      const start = Math.max(lower, Math.min(segment.end - 0.25, segment.start + delta));
      segment.start = start;
      if (drag.index > 0) original[drag.index - 1].end = start;
    } else if (drag.mode === 'right') {
      const upper = drag.index < original.length - 1 ? original[drag.index + 1].end - 0.25 : duration;
      const end = Math.min(upper, Math.max(segment.start + 0.25, segment.end + delta));
      segment.end = end;
      if (drag.index < original.length - 1) original[drag.index + 1].start = end;
    } else {
      // Move mode: shift entire segment and bump neighbors
      const length = segment.end - segment.start;
      const lower = drag.index > 0 ? original[drag.index - 1].start + 0.25 : 0;
      const upper = drag.index < original.length - 1 ? original[drag.index + 1].end - length - 0.25 : duration - length;
      const start = Math.max(lower, Math.min(upper, segment.start + delta));
      segment.start = start;
      segment.end = start + length;
      if (drag.index > 0) original[drag.index - 1].end = start;
      if (drag.index < original.length - 1) original[drag.index + 1].start = segment.end;
    }
    setProgramPreview(original);
  };

  const finishProgramDrag = (event: PointerEvent<HTMLDivElement>) => {
    const drag = programDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (drag.moved && programPreview) editProgramSegments(programPreview);
    setProgramPreview(null);
    programDrag.current = null;
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName) || event.target.isContentEditable)) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        event.shiftKey ? redoProjectEdit() : undoProjectEdit();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redoProjectEdit();
        return;
      }
      if (event.key.toLowerCase() === 's') {
        event.preventDefault();
        splitProgramAtPlayhead();
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        deleteProgramAtPlayhead();
        return;
      }
      const cameraIndex = Number(event.key) - 1;
      if (cameraIndex >= 0 && cameraIndex < cameras.length) {
        event.preventDefault();
        setProgramCut(cameras[cameraIndex].source, useStore.getState().currentTime);
      }
      if (event.key === ',' || event.key === '.') {
        const camera = cameras.find((item) => item.source === selectedCamera);
        if (!camera) return;
        const delta = event.shiftKey ? 0.001 : 1 / fps;
        const direction = event.key === ',' ? -1 : 1;
        setCameraOffset(camera.source, camera.offset_s + direction * delta);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [cameras, selectedCamera, fps, redoProjectEdit, undoProjectEdit, splitProgramAtPlayhead, deleteProgramAtPlayhead, setProgramCut, setCameraOffset]);

  const step = tickInterval(pxPerSecond);
  const firstVisibleTime = timelineStart + scrollLeft / pxPerSecond;
  const firstTick = Math.floor(firstVisibleTime / step) * step;
  const tickCount = Math.ceil(viewportWidth / (step * pxPerSecond)) + 3;
  const ticks = Array.from({ length: Math.max(1, tickCount) }, (_, index) => firstTick + index * step);
  const playheadX = (currentTime - timelineStart) * pxPerSecond;

  return (
    <div data-tour="program-timeline" className="flex h-full min-h-0 flex-col bg-[#0a0a0c] text-[#ededed]">

      {/* Header Toolbar */}
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-[#2a2a32] bg-[#141418] px-4">
        <div className="mr-4 flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-white">PROGRAM TIMELINE</span>
          <span className="rounded bg-[#2a2a32] px-1.5 py-0.5 text-[9px] font-semibold text-[#a1a1aa]">
            {cameras.length} CAMS
          </span>
        </div>

        <div className="h-4 w-px bg-white/10 mx-1" />

        <button type="button" title="Undo (Ctrl+Z)" disabled={!projectHistory.length} onClick={undoProjectEdit} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white disabled:opacity-30"><Undo2 size={14} /></button>
        <button type="button" title="Redo (Ctrl+Y)" disabled={!projectFuture.length} onClick={redoProjectEdit} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white disabled:opacity-30"><Redo2 size={14} /></button>
        <button type="button" title="Split at Playhead (S)" onClick={splitProgramAtPlayhead} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white"><Scissors size={14} /></button>
        <button type="button" title="Delete Segment" onClick={deleteProgramAtPlayhead} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white"><Trash2 size={14} /></button>
        <button
          type="button"
          data-tour="ai-cuts"
          title={suggestions.length ? 'Apply the AI rough cut to the program track' : 'AI cut suggestions appear after syncing'}
          disabled={!suggestions.length || segments.length > 0}
          onClick={applySuggestedSegments}
          className="flex items-center gap-1 rounded border border-[#00E5FF]/30 px-2 py-1 text-[10px] font-semibold text-[#00E5FF] hover:bg-[#00E5FF]/10 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Wand2 size={12} /> AI Cuts{suggestions.length ? ` · ${suggestions.length}` : ''}
        </button>

        <div className="ml-auto flex items-center gap-1.5">
          <button type="button" onClick={() => setZoom((v) => Math.max(0.001, (v ?? fitZoom) / 1.25))} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white"><ZoomOut size={14} /></button>
          <input aria-label="Zoom" type="range" min="0.001" max="8" step="0.01" value={effectiveZoom} onChange={(e) => setZoom(Number(e.target.value))} className="w-24 accent-[#00E5FF]" />
          <button type="button" onClick={() => setZoom((v) => Math.min(8, (v ?? fitZoom) * 1.25))} className="rounded p-1.5 text-[#a1a1aa] hover:bg-white/10 hover:text-white"><ZoomIn size={14} /></button>
          <button type="button" onClick={() => setZoom(null)} className="rounded border border-white/10 px-2 py-1 text-[10px] font-semibold text-[#a1a1aa] hover:border-[#00E5FF] hover:text-[#00E5FF]">FIT</button>
        </div>
      </header>

      {/* Main Timeline Area */}
      <div
        data-tour="timeline-trimming"
        ref={viewportRef}
        className="relative flex-1 overflow-x-auto overflow-y-hidden bg-[#0c0c10] cursor-crosshair"
        onScroll={(e) => setScrollLeft(e.currentTarget.scrollLeft)}
        onPointerDown={scrubPointerDown}
        onPointerMove={scrubPointerMove}
        onPointerUp={(e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
      >
        <div className="relative h-full" style={{ width: contentWidth }}>

          {/* Timecode Ruler */}
          <div className="sticky top-0 z-40 h-8 border-b border-[#2a2a32] bg-[#141418]/95 backdrop-blur-sm">
            {ticks.map((tick) => (
              <div key={tick} className="absolute inset-y-0 border-l border-white/10" style={{ left: (tick - timelineStart) * pxPerSecond }}>
                <span className="absolute left-1.5 top-1/2 -translate-y-1/2 font-mono text-[9px] text-[#71717a]">
                  {formatTimecode(tick, fps)}
                </span>
              </div>
            ))}
          </div>

          {/* Single Program Track */}
          <div className="absolute inset-x-0 top-8 bottom-0 bg-[#08080b]">
            {activeSegments.length === 0 ? (
              // 9-Step / Empty State Tutorial
              <div className="flex h-full items-center justify-center">
                <div data-tour="manual-override" className="text-center space-y-4 max-w-sm">
                  <div className="text-sm font-semibold text-white">Timeline Empty</div>
                  <p className="text-xs text-[#a1a1aa]">
                    Your footage is synced. Apply the AI rough cut or press <kbd className="bg-white/10 px-1 rounded">1</kbd> - <kbd className="bg-white/10 px-1 rounded">8</kbd> to start cutting.
                  </p>
                  {suggestions.length > 0 && (
                    <button
                      onClick={applySuggestedSegments}
                      className="mx-auto flex items-center gap-2 rounded bg-[#00E5FF] px-4 py-2 text-xs font-bold text-[#04181c] hover:bg-[#33ecff] transition-colors"
                    >
                      <Wand2 size={14} /> Apply AI Rough Cut
                    </button>
                  )}
                </div>
              </div>
            ) : (
              // Render Segments
              <div className="relative h-[100px] border-b border-[#2a2a32]">
                {activeSegments.map((segment, index) => {
                  const cameraIndex = cameras.findIndex((camera) => camera.source === segment.camera);
                  const camera = cameras[cameraIndex];
                  const color = CAMERA_COLORS[Math.max(0, cameraIndex) % CAMERA_COLORS.length];
                  const segmentWidth = Math.max(4, (segment.end - segment.start) * pxPerSecond);
                  const isPlayheadSegment = currentTime >= segment.start && currentTime < segment.end;

                  return (
                    <div
                      key={segment.id ?? `${segment.camera}-${segment.start}-${index}`}
                      data-interactive="true"
                      className={`absolute inset-y-2 z-10 cursor-grab overflow-hidden rounded border bg-[#141418] shadow-lg active:cursor-grabbing transition-shadow ${isPlayheadSegment ? 'shadow-[0_0_15px_rgba(0,229,255,0.3)] ring-1 ring-[#00E5FF]' : 'hover:border-white/70'}`}
                      style={{
                        left: (segment.start - timelineStart) * pxPerSecond,
                        width: segmentWidth,
                        borderColor: isPlayheadSegment ? '#00E5FF' : `${color}99`,
                        backgroundColor: `${color}18`,
                      }}
                      title={`${segment.camera} · ${formatTimecode(segment.start, fps)}–${formatTimecode(segment.end, fps)}`}
                      onPointerDown={(event) => beginProgramDrag(index, event)}
                      onPointerMove={moveProgramDrag}
                      onPointerUp={finishProgramDrag}
                      onPointerCancel={finishProgramDrag}
                    >
                      {/* Background Filmstrip */}
                      {cameraIndex >= 0 && (
                        <SegmentFilmstrip
                          sessionId={sessionId}
                          cameraIndex={cameraIndex}
                          segment={segment}
                          cameraOffset={Number(camera?.offset_s ?? 0)}
                          sourceDuration={Number(camera?.duration_sec ?? duration)}
                          timelineStart={timelineStart}
                          pxPerSecond={pxPerSecond}
                          scrollLeft={scrollLeft}
                          viewportWidth={viewportWidth}
                        />
                      )}

                      {/* Segment Overlay Gradient for text readability */}
                      <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />

                      {/* Segment Label */}
                      <span className="pointer-events-none absolute left-2 bottom-2 z-20 flex items-center gap-1.5 rounded-sm bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white backdrop-blur-sm">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
                        {segment.camera}
                      </span>
                      <span className="pointer-events-none absolute bottom-2 right-2 z-20 rounded-sm bg-black/70 px-1 py-0.5 font-mono text-[8px] text-white/90">
                        {formatTimecode(segment.start, fps)}–{formatTimecode(segment.end, fps)}
                      </span>
                      <select
                        aria-label={`Change camera for cut ${index + 1}`}
                        data-tour={index === 0 ? 'manual-override' : undefined}
                        value={segment.camera}
                        onPointerDown={(event) => event.stopPropagation()}
                        onChange={(event) => {
                          const camera = event.currentTarget.value;
                          editProgramSegments(segments.map((item, itemIndex) => itemIndex === index
                            ? { ...item, camera, source: 'manual', reason: 'Manual camera override' }
                            : item));
                        }}
                        className="absolute right-1 top-1 z-30 max-w-[42%] rounded border border-white/20 bg-black/75 px-1 py-0.5 text-[9px] text-white"
                      >
                        {cameras.map((item) => (
                          <option key={item.source} value={item.source}>{item.source}</option>
                        ))}
                      </select>

                      {/* Trim Handles */}
                      <span data-tour={index === 0 ? 'timeline-trim-edge' : undefined} className="absolute inset-y-0 left-0 z-30 w-1.5 cursor-ew-resize bg-white/10 hover:bg-[#00E5FF] transition-colors" />
                      <span className="absolute inset-y-0 right-0 z-30 w-1.5 cursor-ew-resize bg-white/10 hover:bg-[#00E5FF] transition-colors" />
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Global Playhead */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 top-0 z-50 w-px bg-[#00E5FF] shadow-[0_0_8px_#00E5FF]"
            style={{ left: playheadX }}
          >
            {/* Playhead handle */}
            <div className="absolute left-1/2 top-1 h-3 w-3 -translate-x-1/2 rounded-sm bg-[#00E5FF] rotate-45 transform origin-center" />
          </div>

        </div>
      </div>
    </div>
  );
}