import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Expand, FastForward, Pause, Play, Rewind, SkipBack, SkipForward, Volume2 } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useEditorStore } from '@/store/useEditorStore';

function formatTimecode(seconds: number) {
  const safe = Math.max(0, seconds);
  const whole = Math.floor(safe);
  const frames = Math.floor((safe - whole) * 100);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remaining = whole % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}.${String(frames).padStart(2, '0')}`;
}

export default function ProgramMonitor() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [volume, setVolume] = useState(0.8);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);

  const allSources = useStore((state) => state.allSources);
  const files = useStore((state) => state.files);
  const cameras = useStore((state) => state.syncData);
  const studioDuration = useStore((state) => state.duration);
  const currentTime = useEditorStore((state) => state.playheadPosition);
  const isPlaying = useEditorStore((state) => state.isPlaying);
  const clips = useEditorStore((state) => state.clips);
  const activeClipId = useEditorStore((state) => state.activeClipId);
  const selectedSourceIndex = useEditorStore((state) => state.selectedSourceIndex);
  const setPlayhead = useEditorStore((state) => state.setPlayhead);
  const setIsPlaying = useEditorStore((state) => state.setIsPlaying);

  const activeClip = clips.find((clip) => currentTime >= clip.start && currentTime < clip.start + clip.duration) ?? clips.find((clip) => clip.id === activeClipId) ?? null;
  const sourceIndex = isPlaying ? activeClip?.sourceIndex ?? selectedSourceIndex ?? 0 : selectedSourceIndex ?? activeClip?.sourceIndex ?? 0;
  const src = activeClip?.sourceIndex === sourceIndex && activeClip.sourceUrl ? activeClip.sourceUrl : allSources[sourceIndex] ?? activeClip?.sourceUrl ?? null;

  const camera = cameras[sourceIndex];
  const sourceName = camera?.source || files[sourceIndex]?.name?.replace(/\.[^.]+$/, '') || activeClip?.name || 'Program';
  const cameraOffset = Number(camera?.offset_s ?? 0);
  const duration = Math.max(studioDuration, ...clips.map((clip) => clip.start + clip.duration), 0);

  const activeTransform = activeClip && activeClip.sourceIndex === sourceIndex ? `translate(${activeClip.positionX}px, ${activeClip.positionY}px) rotate(${activeClip.rotation}deg) scale(${activeClip.scale / 100})` : undefined;
  const monitorStyle = useMemo(() => ({ transform: activeTransform, opacity: activeClip?.sourceIndex === sourceIndex ? activeClip.opacity / 100 : 1 }), [activeClip, activeTransform, sourceIndex]);

  const seekPlayerToPlayhead = useCallback((time: number) => {
    const player = videoRef.current;
    if (!player || player.readyState < 1) return;

    // WHY: The target time in the original video is (Global Time - Sync Offset).
    const target = Math.max(0, time - cameraOffset);

    if (Math.abs(player.currentTime - target) > 0.05) {
      try {
        player.currentTime = Math.min(target, Number.isFinite(player.duration) ? player.duration : target);
      } catch {
        // Browsers can reject a seek while the source is changing.
      }
    }
  }, [cameraOffset]);

  useEffect(() => { seekPlayerToPlayhead(currentTime); }, [currentTime, src, seekPlayerToPlayhead]);
  useEffect(() => { setMediaError(null); }, [src]);

  useEffect(() => {
    const player = videoRef.current;
    if (!player) return;
    player.volume = volume;
    player.playbackRate = playbackRate;
  }, [volume, playbackRate, src]);

  useEffect(() => {
    const player = videoRef.current;
    if (!player) return;
    if (!isPlaying) { player.pause(); return; }
    player.play().catch(() => setIsPlaying(false));
  }, [isPlaying, src, setIsPlaying]);

  useEffect(() => {
    if (isPlaying) return;
    useStore.getState().setCurrentTime(currentTime);
  }, [currentTime, isPlaying]);

  useEffect(() => {
    if (!isPlaying) return;
    let frame = 0;
    let lastUpdate = 0;
    const updateClock = (now: number) => {
      const player = videoRef.current;
      if (!player) return;

      if (!player.paused && player.readyState >= 2 && now - lastUpdate >= 32) {
        const sourceTime = player.currentTime;
        const globalTime = sourceTime + cameraOffset;

        const clipAtTime = useEditorStore.getState().clips.find((clip) =>
          globalTime >= clip.start && globalTime < clip.start + clip.duration,
        );

        if (clipAtTime) {
          if (clipAtTime.id !== activeClip?.id) {
            useEditorStore.getState().setActiveClip(clipAtTime.id);
            useEditorStore.getState().setPlayhead(globalTime);
          } else {
            useEditorStore.getState().setPlayhead(Math.min(duration || globalTime, globalTime));
          }
        }
        lastUpdate = now;
      }
      frame = requestAnimationFrame(updateClock);
    };
    frame = requestAnimationFrame(updateClock);
    return () => cancelAnimationFrame(frame);
  }, [isPlaying, cameraOffset, duration, activeClip]);

  useEffect(() => {
    const onFullscreen = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFullscreen);
    return () => document.removeEventListener('fullscreenchange', onFullscreen);
  }, []);

  const handleLoadedMetadata = () => {
    const time = useEditorStore.getState().playheadPosition;
    seekPlayerToPlayhead(time);
    if (useEditorStore.getState().isPlaying) videoRef.current?.play().catch(() => setIsPlaying(false));
  };

  const seekBy = (seconds: number) => { setPlayhead(Math.max(0, Math.min(duration, currentTime + seconds))); };
  const toggleFullscreen = () => {
    const monitor = videoRef.current?.parentElement;
    if (!monitor) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void monitor.requestFullscreen?.();
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-panel">
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-2 text-xs font-semibold text-text">
          <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_8px_#06b6d4]" />
          PROGRAM
          {activeClip && <span className="max-w-48 truncate text-muted">· {activeClip.name}</span>}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted">
          <span>{sourceName}</span>
          {camera?.state && <span className="rounded border border-border px-2 py-0.5">{camera.state}</span>}
        </div>
      </div>

      <div data-tour="program-monitor" className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black">
        {src ? (
          <video ref={videoRef} src={src} muted={false} playsInline preload="auto" onLoadedMetadata={handleLoadedMetadata} onEnded={() => setIsPlaying(false)} onError={() => { setMediaError('This video could not be decoded or is no longer available.'); setIsPlaying(false); }} className="h-full w-full object-contain" style={monitorStyle} />
        ) : (
          <div className="flex flex-col items-center gap-3 text-center">
            <div className="grid h-16 w-16 place-items-center rounded-2xl border border-accent/20 bg-accent/10 text-accent"><Play size={24} /></div>
            <div>
              <p className="text-base font-semibold text-text">Program Monitor</p>
              <p className="mt-1 text-sm text-muted">Import and sync camera media to begin editing.</p>
            </div>
          </div>
        )}
        {mediaError && <div role="alert" className="absolute inset-x-4 bottom-12 mx-auto max-w-md rounded-md border border-rose-500/30 bg-black/85 px-3 py-2 text-center text-sm text-rose-200">{mediaError}</div>}
        {src && (
          <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-md border border-border bg-black/75 px-3 py-1.5 font-mono text-xs text-white shadow-lg">
            <span className="text-accent">{formatTimecode(currentTime)}</span>
            <span className="mx-1.5 text-muted">/</span>
            <span>{formatTimecode(duration)}</span>
            <span className="ml-2 text-muted">Remaining: {formatTimecode(Math.max(0, duration - currentTime))}</span>
          </div>
        )}
      </div>

      <div data-tour="playback-controls" className="flex h-14 shrink-0 items-center gap-2 border-t border-border px-4">
        <button type="button" aria-label="Go to start" onClick={() => setPlayhead(0)} className="grid h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 hover:text-text"><SkipBack size={16} /></button>
        <button type="button" aria-label="Back five seconds" onClick={() => seekBy(-5)} className="grid h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 hover:text-text"><Rewind size={16} /></button>
        <button type="button" aria-label={isPlaying ? 'Pause' : 'Play'} onClick={() => setIsPlaying(!isPlaying)} disabled={!src} className="grid h-10 w-10 place-items-center rounded-full bg-accent text-[#07191d] hover:bg-cyan-300 disabled:opacity-40">
          {isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
        </button>
        <button type="button" aria-label="Forward five seconds" onClick={() => seekBy(5)} className="grid h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 hover:text-text"><FastForward size={16} /></button>
        <button type="button" aria-label="Go to end" onClick={() => setPlayhead(duration)} className="grid h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 hover:text-text"><SkipForward size={16} /></button>
        <div className="ml-2 min-w-[180px] whitespace-nowrap font-mono text-xs">
          <span className="text-accent">{formatTimecode(currentTime)}</span>
          <span className="mx-1.5 text-muted">/</span>
          <span className="text-text">{formatTimecode(duration)}</span>
          <span className="ml-1.5 text-muted">−{formatTimecode(Math.max(0, duration - currentTime))}</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <select aria-label="Playback speed" value={playbackRate} onChange={(event) => setPlaybackRate(Number(event.currentTarget.value))} className="h-8 rounded border border-border bg-background px-2 text-xs text-text">
            <option value="0.5">0.5×</option><option value="1">1.0×</option><option value="1.5">1.5×</option><option value="2">2.0×</option>
          </select>
          <Volume2 size={16} className="text-muted" />
          <input aria-label="Volume" type="range" min="0" max="1" step="0.05" value={volume} onChange={(event) => setVolume(Number(event.currentTarget.value))} className="w-20 accent-accent" />
          <button type="button" aria-label="Toggle fullscreen" onClick={toggleFullscreen} className="grid h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 hover:text-text"><Expand size={16} /></button>
          <span className="sr-only">{isFullscreen ? 'Fullscreen active' : 'Fullscreen inactive'}</span>
        </div>
      </div>
    </div>
  );
}