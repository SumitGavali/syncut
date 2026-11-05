import { useEffect, useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { Check, MoreHorizontal } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useEditorStore, type EditorClip as EditorClipType } from '@/store/useEditorStore';

const THUMBNAIL_BACKGROUND = `url("data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="48" viewBox="0 0 96 48"><rect width="96" height="48" fill="#0b1820"/><g opacity=".32"><rect x="3" y="4" width="42" height="40" fill="#cffafe"/><path d="M3 32 15 20l9 8 8-11 13 14v13H3Z" fill="#0e7490"/><rect x="51" y="4" width="42" height="40" fill="#dbeafe"/><path d="m51 31 12-10 8 7 9-12 13 14v14H51Z" fill="#155e75"/></g><path d="M48 0v48" stroke="#fff" stroke-opacity=".3"/>'
)}")`;

interface TimelineClipProps {
  clip: EditorClipType;
  pixelsPerSecond: number;
  isActive: boolean;
  onCameraOverride?: (clips: EditorClipType[]) => void;
}

interface ContextMenuPosition {
  x: number;
  y: number;
}

function formatClipTime(seconds: number) {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const remaining = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`;
}

export default function TimelineClip({
  clip,
  pixelsPerSecond,
  isActive,
  onCameraOverride,
}: TimelineClipProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: clip.id });
  const cameras = useStore((state) => state.syncData);
  const localSources = useStore((state) => state.allSources);
  const availableCameras = cameras.length
    ? cameras.map((camera, index) => ({
      name: camera.source,
      sourceIndex: index,
      sourceUrl: localSources[index],
    }))
    : useEditorStore.getState().clips.map((item) => ({
      name: item.name,
      sourceIndex: item.sourceIndex,
      sourceUrl: item.sourceUrl,
    })).filter((camera, index, list) => list.findIndex((item) => item.name === camera.name) === index);
  const setActiveClip = useEditorStore((state) => state.setActiveClip);
  const setPlayhead = useEditorStore((state) => state.setPlayhead);
  const setClipCamera = useEditorStore((state) => state.setClipCamera);
  const setSelectedSourceIndex = useEditorStore((state) => state.setSelectedSourceIndex);
  const [contextMenu, setContextMenu] = useState<ContextMenuPosition | null>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener('pointerdown', close);
    window.addEventListener('blur', close);
    return () => {
      window.removeEventListener('pointerdown', close);
      window.removeEventListener('blur', close);
    };
  }, [contextMenu]);

  const confidence = typeof clip.confidence === 'number' && Number.isFinite(clip.confidence)
    ? Math.max(0, Math.min(100, clip.confidence <= 1 ? clip.confidence * 100 : clip.confidence))
    : null;
  const width = Math.max(38, clip.duration * pixelsPerSecond);

  return (
    <>
      <div
        ref={setNodeRef}
        {...attributes}
        {...listeners}
        data-timeline-interactive="true"
        role="button"
        tabIndex={0}
        aria-label={`${clip.name}, ${formatClipTime(clip.start)} to ${formatClipTime(clip.start + clip.duration)}`}
        onClick={() => {
          setActiveClip(clip.id);
          setSelectedSourceIndex(null);
          setPlayhead(clip.start);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setContextMenu({ x: event.clientX, y: event.clientY });
          setActiveClip(clip.id);
        }}
        style={{
          left: clip.start * pixelsPerSecond,
          width,
          borderColor: clip.color,
          transform: CSS.Translate.toString(transform),
          opacity: clip.opacity / 100,
          zIndex: isDragging ? 40 : isActive ? 20 : 10,
        }}
        className={`group absolute inset-y-1.5 touch-none select-none overflow-hidden rounded-md border-2 shadow-lg transition-shadow ${
          isDragging
            ? 'cursor-grabbing shadow-[0_8px_24px_rgba(0,0,0,0.5)]'
            : 'cursor-grab hover:brightness-110'
        } ${isActive ? 'ring-1 ring-accent/70' : ''}`}
      >
        <div aria-hidden="true" className="absolute inset-0" style={{ backgroundColor: clip.color, opacity: 0.2 }} />
        {clip.sourceUrl && (
          <video
            aria-hidden="true"
            src={clip.sourceUrl}
            muted
            preload="metadata"
            tabIndex={-1}
            onLoadedMetadata={(event) => {
              const video = event.currentTarget;
              if (Number.isFinite(video.duration) && video.duration > 0) {
                video.currentTime = Math.min(0.15, video.duration / 2);
              }
            }}
            className="absolute inset-0 h-full w-full object-cover opacity-35"
          />
        )}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage: THUMBNAIL_BACKGROUND,
            backgroundRepeat: 'repeat-x',
            backgroundSize: '96px 100%',
            opacity: 0.18,
          }}
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/15 via-transparent to-black/65" />
        <div className="absolute inset-x-0 top-1 flex items-center justify-between gap-1 px-2">
          <span className="flex min-w-0 items-center gap-1.5 truncate text-[11px] font-bold text-white drop-shadow">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: clip.color }} />
            <span className="truncate">{clip.name}</span>
          </span>
          <span className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-bold ${
            confidence === null
              ? 'bg-gray-700/80 text-gray-300'
              : confidence >= 60
                ? 'bg-emerald-500/80 text-white'
                : 'bg-rose-500/80 text-white'
          }`}>
            {confidence === null ? '—' : `${confidence.toFixed(0)}%`}
          </span>
        </div>
        {width > 95 && (
          <div className="absolute inset-x-2 bottom-1 flex items-center justify-between gap-1 font-mono text-[9px] text-gray-200 drop-shadow">
            <span>{formatClipTime(clip.start)}</span>
            <span>{formatClipTime(clip.start + clip.duration)}</span>
          </div>
        )}
        <button
          type="button"
          aria-label={`Clip options for ${clip.name}`}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            setContextMenu({ x: event.clientX, y: event.clientY });
          }}
          className="absolute bottom-1 right-1 z-20 rounded bg-black/50 p-0.5 text-white/80 opacity-0 hover:text-white group-hover:opacity-100 focus:opacity-100"
        >
          <MoreHorizontal size={13} />
        </button>
      </div>
      {contextMenu && (
        <div
          data-timeline-interactive="true"
          data-tour="manual-override"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onPointerDown={(event) => event.stopPropagation()}
          className="fixed z-[100] min-w-48 rounded-lg border border-border bg-panel p-1.5 shadow-2xl"
        >
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Override Camera</p>
          {availableCameras.map((camera) => (
            <button
              key={camera.name}
              type="button"
              onClick={() => {
                setClipCamera(clip.id, camera.name, camera.sourceIndex, camera.sourceUrl);
                onCameraOverride?.(useEditorStore.getState().clips);
                setContextMenu(null);
              }}
              className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs text-gray-200 hover:bg-white/10"
            >
              <span>{camera.name}</span>
              {camera.name === clip.name && <Check size={13} className="text-accent" />}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
