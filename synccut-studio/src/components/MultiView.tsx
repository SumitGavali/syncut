/** Synchronized camera previews follow the shared program timeline clock. */
import { useEffect, useRef, useCallback, useState, type CSSProperties } from 'react';
import { Film, Maximize, Pause, Play, SkipBack, SkipForward, Volume2, Zap } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { getActiveCamera } from '@/lib/activeCamera';
import { cn, formatTC } from '@/lib/utils';
import { Button } from '@/components/ui/button';

type Player = HTMLVideoElement;

const CAM_ACCENTS = [
  '#00E5FF', // A – cyan
  '#34d399', // B – emerald
  '#f59e0b', // C – amber
  '#a78bfa', // D – violet
  '#f87171', // E – rose
  '#38bdf8', // F – sky
  '#fb923c', // G – orange
  '#e879f9', // H – fuchsia
];

function inferMediaType(fileName: string | undefined) {
  const extension = fileName?.split('.').pop()?.toLowerCase();
  const types: Record<string, string> = {
    mp4: 'video/mp4',
    m4v: 'video/mp4',
    mov: 'video/quicktime',
    mkv: 'video/x-matroska',
    avi: 'video/x-msvideo',
    webm: 'video/webm',
    mts: 'video/mp2t',
    m2ts: 'video/mp2t',
    ts: 'video/mp2t',
    mp3: 'audio/mpeg',
    wav: 'audio/wav',
    m4a: 'audio/mp4',
    aac: 'audio/aac',
    flac: 'audio/flac',
    ogg: 'audio/ogg',
  };
  return extension ? types[extension] : undefined;
}

// ─────────────────────────────────────────────
// Single camera pane
// ─────────────────────────────────────────────
interface PaneProps {
  index: number;
  cameraName: string;
  src: string | null;
  sourceType?: string;
  muted?: boolean;
  active: boolean;
  offset: number | null;
  state?: string;
  playbackRate: number;
  layoutStyle: CSSProperties;
  onTake: () => void;
  onPlayer: (index: number, p: Player | null) => void;
}

function VideoPane({
  index,
  cameraName,
  src,
  sourceType,
  muted,
  active,
  offset,
  state,
  playbackRate,
  layoutStyle,
  onTake,
  onPlayer,
}: PaneProps) {
  const player = useRef<HTMLVideoElement>(null);
  const [mediaError, setMediaError] = useState(false);
  const videoPaneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!player.current) return;
    onPlayer(index, player.current);
    return () => {
      onPlayer(index, null);
      player.current?.pause();
      player.current?.removeAttribute('src');
      player.current?.load();
    };
  }, [index, onPlayer]);

  useEffect(() => {
    setMediaError(false);
  }, [src]);

  useEffect(() => {
    if (player.current) player.current.muted = muted ?? true;
  }, [muted]);

  useEffect(() => {
    if (player.current) player.current.playbackRate = playbackRate;
  }, [playbackRate]);

  const accent = CAM_ACCENTS[index % CAM_ACCENTS.length];
  const shortName = cameraName.replace(/^Camera\s*/i, '') || String(index + 1);
  const audioOnlySource = sourceType?.startsWith('audio/') ?? false;
  const hasVideoSource = Boolean(src) && !audioOnlySource;
  const enterFullscreen = () => {
    void videoPaneRef.current?.requestFullscreen?.();
  };

  return (
    <div
      ref={videoPaneRef}
      data-tour={active ? 'active-camera' : undefined}
      style={layoutStyle}
      className={cn(
        'relative min-h-0 min-w-0 overflow-hidden rounded-lg border-2 bg-black transition-colors duration-200',
        active
          ? 'border-[#00E5FF] opacity-100 z-10 shadow-[0_0_22px_rgba(0,229,255,0.3)]'
          : 'border-white/10 opacity-75 hover:border-white/30 cursor-pointer',
      )}
      onClick={!active ? onTake : undefined}
    >
      <video
        ref={player}
        className="absolute inset-0 h-full w-full bg-black object-contain"
        src={src ?? undefined}
        preload={active ? 'auto' : 'metadata'}
        playsInline
        onError={() => setMediaError(true)}
        onLoadedData={() => setMediaError(false)}
      />

      {/* Placeholder when no video stream is available */}
      {!hasVideoSource && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-[#0c0c12] text-xs text-[#71717a]">
          <div
            className="w-8 h-8 rounded-full border-2 border-dashed flex items-center justify-center"
            style={{ borderColor: accent + '55' }}
          >
            <span className="font-bold text-sm" style={{ color: accent }}>
              {index + 1}
            </span>
          </div>
          <span>{audioOnlySource ? `${cameraName} · audio only` : `No video file · ${cameraName}`}</span>
        </div>
      )}
      {active && hasVideoSource && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            enterFullscreen();
          }}
          aria-label="Full-screen preview"
          className="absolute bottom-2 right-2 z-20 rounded border border-white/20 bg-black/75 p-1.5 text-white hover:border-[#00E5FF] hover:text-[#00E5FF]"
        >
          <Maximize size={14} />
        </button>
      )}

      {/* Camera label badge */}
      <div
        className={cn(
          'absolute left-2 top-2 z-20 rounded px-2 py-0.5 text-[10px] font-bold tracking-wider transition-all',
          active ? 'bg-[#00E5FF] text-[#04181c]' : 'bg-black/60 text-white/60',
        )}
      >
        {cameraName}
      </div>

      <div className="absolute right-2 top-2 z-20 rounded bg-black/70 px-1.5 py-1 font-mono text-[9px] text-white/80">
        <span className="mr-1.5">{state ?? 'Not measured'}</span>
        <span className="text-[#00E5FF]">
          {offset === null ? 'Not measured' : `${offset >= 0 ? '+' : ''}${offset.toFixed(3)} s`}
        </span>
      </div>

      {mediaError && hasVideoSource && (
        <div className="absolute inset-0 z-10 grid place-items-center bg-black/75 px-4 text-center text-xs text-amber-200">
          Unable to load this camera source.
        </div>
      )}

      {/* Active ON-AIR indicator */}
      {active && hasVideoSource && (
        <div className="absolute bottom-2 left-2 z-20 flex items-center gap-1 rounded-sm bg-black/70 px-1.5 py-0.5 backdrop-blur">
          <span className="h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse" />
          <span className="text-[9px] font-bold text-white tracking-wider">ON AIR · {shortName}</span>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Main MultiView component
// ─────────────────────────────────────────────
export default function MultiView() {
  // Dynamic set of players – keyed by camera index
  const playersRef = useRef<Map<number, Player>>(new Map());
  const masterAudioRef = useRef<HTMLAudioElement>(null);

  const allSources = useStore((s) => s.allSources);
  const files = useStore((s) => s.files);
  const isPlaying = useStore((s) => s.isPlaying);
  const playbackRate = useStore((s) => s.playbackRate);
  const duration = useStore((s) => s.duration);
  const currentTime = useStore((s) => s.currentTime);
  const segments = useStore((s) => s.segments);
  const overrides = useStore((s) => s.manualOverrides);
  const syncData = useStore((s) => s.syncData);
  const masterCamera = useStore((s) => s.masterCamera);
  const masterAudioUrl = useStore((s) => s.masterAudioUrl);
  const fps = useStore((s) => s.fps);
  const setPlaybackRate = useStore((s) => s.setPlaybackRate);
  const setSelectedCamera = useStore((s) => s.setSelectedCamera);
  const setProgramCut = useStore((s) => s.setProgramCut);

  const [volume, setVolume] = useState(1);

  const cameraNames = Array.from({ length: allSources.length }, (_, index) => {
    const syncedName = syncData[index]?.source;
    const fileName = files[index]?.name || syncData[index]?.file;
    return syncedName || fileName?.replace(/\.[^.]+$/, '') || `Camera ${index + 1}`;
  });
  const camCount = allSources.length;
  const masterIndex = Math.max(0, syncData.findIndex((camera) => camera.is_master));

  const activeCamera = getActiveCamera(currentTime, segments, overrides);
  const onAir = activeCamera ?? masterCamera ?? syncData[masterIndex]?.source ?? cameraNames[0] ?? null;
  const activeIndex = Math.max(0, cameraNames.indexOf(onAir ?? ''));
  const timelineOrigin = Math.min(0, ...syncData.map((camera) => Number(camera.offset_s ?? 0)));
  const resolvedMasterAudioUrl = masterAudioUrl
    ? new URL(masterAudioUrl, import.meta.env.VITE_API_BASE || window.location.origin).toString()
    : null;

  const clockIndex = syncData.reduce((bestIndex, camera, index, cameras) => {
    if (Number(camera.offset_s ?? 0) > 0) return bestIndex;
    const best = cameras[bestIndex];
    return Number(camera.offset_s ?? 0) + Number(camera.duration_sec ?? 0) >
      Number(best?.offset_s ?? 0) + Number(best?.duration_sec ?? 0)
      ? index
      : bestIndex;
  }, masterIndex);

  const syncPlayersAt = useCallback((globalTime: number) => {
    const currentSyncData = useStore.getState().syncData;
    const state = useStore.getState();
    const programCamera = getActiveCamera(
      state.currentTime,
      state.segments,
      state.manualOverrides,
    ) ?? state.masterCamera ?? currentSyncData[clockIndex]?.source;
    const programIndex = Math.max(
      0,
      currentSyncData.findIndex((camera) => camera.source === programCamera),
    );
    playersRef.current.forEach((player, index) => {
      if (state.isPlaying && (
        state.masterAudioUrl
          ? index !== programIndex
          : index !== clockIndex && index !== programIndex
      )) return;
      const offset = Number(currentSyncData[index]?.offset_s ?? 0);
      const localTime = globalTime - offset;
      const sourceDuration = Number(currentSyncData[index]?.duration_sec ?? 0);
      if (sourceDuration > 0 && localTime > sourceDuration) {
        player.pause();
        return;
      }
      const target = Math.max(0, localTime);
      const frameRate = Number(currentSyncData[index]?.frame_rate ?? fps);
      try {
        if (player.readyState >= 1 && Math.abs(player.currentTime - target) > 1 / Math.max(1, frameRate)) {
          player.currentTime = target;
        }
      } catch {
        // The player may not have loaded metadata yet.
      }
    });
  }, [fps, clockIndex]);

  const clockFrame = useRef<number | null>(null);
  const registerPlayer = useCallback((idx: number, p: Player | null) => {
    if (p) playersRef.current.set(idx, p);
    else playersRef.current.delete(idx);
  }, []);

  useEffect(() => {
    if (resolvedMasterAudioUrl) return;
    const master = playersRef.current.get(clockIndex);
    if (!master) return;
    const state = useStore.getState();
    let lastStoreUpdate = 0;
    const stopClock = () => {
      if (clockFrame.current !== null) cancelAnimationFrame(clockFrame.current);
      clockFrame.current = null;
    };
    const startClock = () => {
      stopClock();
      const tick = () => {
        if (master.paused) {
          clockFrame.current = null;
          return;
        }
        const sync = useStore.getState().syncData;
        const globalTime = (Number.isFinite(master.currentTime) ? master.currentTime : 0) +
          Number(sync[clockIndex]?.offset_s ?? 0);
        const totalDuration = useStore.getState().duration;
        if (totalDuration > 0 && globalTime >= totalDuration) {
          useStore.getState().setCurrentTime(totalDuration);
          master.pause();
          useStore.getState().setIsPlaying(false);
          clockFrame.current = null;
          return;
        }
        const now = performance.now();
        if (now - lastStoreUpdate >= 33) {
          useStore.getState().setCurrentTime(globalTime);
          lastStoreUpdate = now;
        }
        syncPlayersAt(globalTime);
        clockFrame.current = requestAnimationFrame(tick);
      };
      clockFrame.current = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      state.setIsPlaying(true);
      const sync = useStore.getState().syncData;
      const globalTime = (Number.isFinite(master.currentTime) ? master.currentTime : 0) +
        Number(sync[clockIndex]?.offset_s ?? 0);
      syncPlayersAt(globalTime);
      playersRef.current.forEach((player, index) => {
        const state = useStore.getState();
        const activeName = getActiveCamera(
          state.currentTime,
          state.segments,
          state.manualOverrides,
        ) ?? state.masterCamera ?? sync[masterIndex]?.source;
        const activeIndex = Math.max(
          0,
          sync.findIndex((camera) => camera.source === activeName),
        );
        if (index === clockIndex || index === activeIndex) {
          player.play()?.catch(() => { });
        } else {
          player.pause();
        }
      });
      startClock();
    };
    const onPause = () => {
      state.setIsPlaying(false);
      stopClock();
      playersRef.current.forEach((player, index) => {
        if (index !== masterIndex) {
          try { player.pause(); } catch { /* Player may already be disposed. */ }
        }
      });
    };
    const onTimeUpdate = () => {
      const sync = useStore.getState().syncData;
      const globalTime = (Number.isFinite(master.currentTime) ? master.currentTime : 0) +
        Number(sync[clockIndex]?.offset_s ?? 0);
      useStore.getState().setCurrentTime(globalTime);
      syncPlayersAt(globalTime);
    };
    const onMetadata = () => {
      const sync = useStore.getState().syncData;
      const knownEnd = sync.reduce(
        (end, camera) => Math.max(end, Number(camera.offset_s ?? 0) + Number(camera.duration_sec ?? 0)),
        0,
      );
      useStore.getState().setDuration(knownEnd || (
        (Number.isFinite(master.duration) ? master.duration : 0) +
        Number(sync[clockIndex]?.offset_s ?? 0)
      ));
    };
    const onEnded = () => {
      useStore.getState().setCurrentTime(useStore.getState().duration);
      useStore.getState().setIsPlaying(false);
    };
    master.addEventListener('play', onPlay);
    master.addEventListener('pause', onPause);
    master.addEventListener('timeupdate', onTimeUpdate);
    master.addEventListener('loadedmetadata', onMetadata);
    master.addEventListener('ended', onEnded);
    return () => {
      master.removeEventListener('play', onPlay);
      master.removeEventListener('pause', onPause);
      master.removeEventListener('timeupdate', onTimeUpdate);
      master.removeEventListener('loadedmetadata', onMetadata);
      master.removeEventListener('ended', onEnded);
      stopClock();
    };
  }, [clockIndex, resolvedMasterAudioUrl, syncPlayersAt, masterIndex]);

  useEffect(() => {
    if (!resolvedMasterAudioUrl) return;
    const audio = masterAudioRef.current;
    if (!audio) return;

    let frame: number | null = null;
    let lastStoreUpdate = 0;
    const stopClock = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
    };
    const startClock = () => {
      stopClock();
      const tick = () => {
        if (audio.paused) {
          frame = null;
          return;
        }
        const globalTime = audio.currentTime + timelineOrigin;
        const totalDuration = useStore.getState().duration;
        if (totalDuration > 0 && globalTime >= totalDuration) {
          useStore.getState().setCurrentTime(totalDuration);
          audio.pause();
          useStore.getState().setIsPlaying(false);
          frame = null;
          return;
        }
        const now = performance.now();
        if (now - lastStoreUpdate >= 33) {
          useStore.getState().setCurrentTime(globalTime);
          lastStoreUpdate = now;
        }
        syncPlayersAt(globalTime);
        frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      useStore.getState().setIsPlaying(true);
      startClock();
    };
    const onPause = () => {
      useStore.getState().setIsPlaying(false);
      stopClock();
    };
    const onEnded = () => {
      useStore.getState().setCurrentTime(useStore.getState().duration);
      useStore.getState().setIsPlaying(false);
      stopClock();
    };
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnded);
    return () => {
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnded);
      stopClock();
    };
  }, [resolvedMasterAudioUrl, syncPlayersAt, timelineOrigin]);

  useEffect(() => {
    if (masterAudioRef.current) masterAudioRef.current.volume = volume;
    playersRef.current.forEach((player, index) => {
      player.volume = volume;
      player.muted = Boolean(resolvedMasterAudioUrl) || index !== activeIndex;
    });
  }, [volume, activeIndex, resolvedMasterAudioUrl]);

  useEffect(() => {
    const knownEnd = syncData.reduce(
      (end, camera) => Math.max(end, Number(camera.offset_s ?? 0) + Number(camera.duration_sec ?? 0)),
      0,
    );
    if (knownEnd > 0) useStore.getState().setDuration(knownEnd);
  }, [syncData]);

  // Scrub from store → master player
  useEffect(() => {
    syncPlayersAt(currentTime);
    const audio = masterAudioRef.current;
    if (!resolvedMasterAudioUrl || !audio || audio.readyState < 1 || isPlaying) return;
    const target = Math.max(0, currentTime - timelineOrigin);
    if (Math.abs(audio.currentTime - target) > 1 / Math.max(fps, 30)) {
      audio.currentTime = target;
    }
  }, [currentTime, fps, isPlaying, resolvedMasterAudioUrl, syncPlayersAt, timelineOrigin]);

  // Keep the program angle moving and pause unused 4K decoders while the mix is the clock.
  useEffect(() => {
    const active = playersRef.current.get(activeIndex);
    const clockPlayer = playersRef.current.get(clockIndex);
    if (resolvedMasterAudioUrl) {
      const audio = masterAudioRef.current;
      if (audio) {
        audio.playbackRate = playbackRate;
        if (isPlaying) {
          if (audio.readyState >= 1) {
            const target = Math.max(0, currentTime - timelineOrigin);
            if (Math.abs(audio.currentTime - target) > 1 / Math.max(fps, 30)) {
              audio.currentTime = target;
            }
          }
          audio.play().catch(() => useStore.getState().setIsPlaying(false));
        } else {
          audio.pause();
        }
      }
      if (isPlaying && active?.paused) {
        syncPlayersAt(currentTime);
        active.play()?.catch(() => useStore.getState().setIsPlaying(false));
      }
      playersRef.current.forEach((player) => {
        if (player !== active) player.pause();
      });
    } else {
      if (!clockPlayer) return;
      if (isPlaying) {
        syncPlayersAt(currentTime);
        [clockPlayer, active].forEach((player) => {
          if (player?.paused) player.play().catch(() => useStore.getState().setIsPlaying(false));
        });
        playersRef.current.forEach((player) => {
          if (player !== clockPlayer && player !== active) player.pause();
        });
      } else {
        playersRef.current.forEach((player) => {
          if (!player.paused) player.pause();
        });
      }
    }
  }, [
    isPlaying,
    activeIndex,
    clockIndex,
    currentTime,
    fps,
    playbackRate,
    resolvedMasterAudioUrl,
    syncPlayersAt,
    timelineOrigin,
  ]);

  return (
    <div className="flex h-full flex-col bg-[#0a0a0c]">
      {resolvedMasterAudioUrl && (
        <audio
          ref={masterAudioRef}
          src={resolvedMasterAudioUrl}
          preload="metadata"
          className="hidden"
        />
      )}

      <div className="flex min-h-0 flex-1 p-2">
        <div
          data-tour="camera-grid"
          className="grid min-h-0 min-w-0 flex-1 gap-2 overflow-hidden"
          style={{
            gridTemplateColumns: camCount > 1 ? 'minmax(0, 3fr) minmax(120px, 1fr)' : 'minmax(0, 1fr)',
            gridTemplateRows: camCount > 1
              ? `repeat(${camCount - 1}, minmax(0, 1fr))`
              : 'minmax(0, 1fr)',
          }}
        >
          {allSources.length ? allSources.map((source, idx) => {
            const name = cameraNames[idx] ?? `Camera ${idx + 1}`;
            const active = idx === activeIndex;
            const thumbnailRow = idx > activeIndex ? idx : idx + 1;
            return (
              <VideoPane
                key={idx}
                index={idx}
                cameraName={name}
                src={source}
                sourceType={files[idx]?.type || inferMediaType(syncData[idx]?.file || files[idx]?.name)}
                muted={Boolean(resolvedMasterAudioUrl) || !active}
                active={active}
                offset={syncData[idx] && !(syncData[idx].state === 'WEAK' && Number(syncData[idx].psr ?? 0) <= 0)
                  ? Number(syncData[idx].offset_s ?? 0)
                  : null}
                state={syncData[idx]?.state}
                playbackRate={playbackRate}
                layoutStyle={{
                  height: '100%',
                  width: '100%',
                  minHeight: 0,
                  gridColumn: active ? '1' : '2',
                  gridRow: active && camCount > 1 ? `1 / span ${camCount - 1}` : active ? '1' : String(thumbnailRow),
                }}
                onTake={() => {
                  setSelectedCamera(name);
                  setProgramCut(name, Math.max(0, currentTime));
                }}
                onPlayer={registerPlayer}
              />
            );
          }) : (
            <div className="col-span-full grid place-items-center rounded-lg border border-dashed border-white/10 text-center">
              <div>
                <Film className="mx-auto mb-2 h-8 w-8 text-[#00E5FF]/70" />
                <p className="text-sm font-semibold text-white">No camera media loaded</p>
                <p className="mt-1 text-xs text-[#71717a]">Import camera files to populate the preview.</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Unified Playback Control Bar */}
      <div data-tour="playback-controls" className="flex h-12 shrink-0 items-center gap-2 border-t border-[#2a2a32] bg-[#141418] px-3">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Back to start"
          className="h-7 w-7 text-[#a1a1aa] hover:text-white"
          onClick={() => useStore.getState().setCurrentTime(0)}
        >
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Step back one frame"
          className="h-7 w-7 text-[#a1a1aa] hover:text-white"
          onClick={() => useStore.getState().setCurrentTime(Math.max(0, currentTime - 1 / fps))}
        >
          <SkipBack className="h-3 w-3" />
        </Button>
        <Button
          size="icon"
          aria-label={isPlaying ? 'Pause' : 'Play'}
          className="h-7 w-7 bg-[#00E5FF] text-[#04181c] hover:bg-[#33ecff]"
          onClick={() => useStore.getState().togglePlay()}
          disabled={allSources.length === 0}
        >
          {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Step forward one frame"
          className="h-7 w-7 text-[#a1a1aa] hover:text-white"
          onClick={() => useStore.getState().setCurrentTime(Math.min(duration, currentTime + 1 / fps))}
        >
          <SkipForward className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous cut"
          className="h-7 w-7 text-[#a1a1aa] hover:text-white"
          onClick={() => {
            const previous = [...segments].reverse().find((segment) => segment.start < currentTime - 1 / fps);
            if (previous) useStore.getState().setCurrentTime(previous.start);
          }}
        >
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Next cut"
          className="h-7 w-7 text-[#a1a1aa] hover:text-white"
          onClick={() => {
            const next = segments.find((segment) => segment.start > currentTime + 1 / fps);
            if (next) useStore.getState().setCurrentTime(next.start);
          }}
        >
          <SkipForward className="h-4 w-4" />
        </Button>

        <div data-tour="timer" className="flex min-w-[190px] items-center gap-1 whitespace-nowrap font-mono text-[11px]">
          <span className="text-[#00E5FF]">{formatTC(currentTime)}</span>
          <span className="text-[#71717a]">/</span>
          <span className="text-white">{formatTC(duration)}</span>
          <span className="ml-1 text-[10px] text-[#a1a1aa]">
            (Remaining: {formatTC(Math.max(0, duration - currentTime))})
          </span>
        </div>
        <input
          aria-label="Seek playback"
          type="range"
          min="0"
          max={Math.max(duration, 0.001)}
          step={1 / Math.max(1, fps)}
          value={Math.min(duration, Math.max(0, currentTime))}
          onChange={(event) => useStore.getState().setCurrentTime(Number(event.currentTarget.value))}
          disabled={duration <= 0}
          className="mx-1 min-w-[70px] flex-1 cursor-pointer accent-[#00E5FF]"
        />
        <Volume2 className="h-3.5 w-3.5 shrink-0 text-[#a1a1aa]" />
        <input
          aria-label="Playback volume"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={volume}
          onChange={(event) => setVolume(Number(event.currentTarget.value))}
          className="hidden w-14 accent-[#00E5FF] sm:block"
        />

        <select
          aria-label="Playback speed"
          value={playbackRate}
          onChange={(event) => setPlaybackRate(Number(event.target.value))}
          className="h-7 rounded border border-white/10 bg-[#0f0f14] px-1.5 text-[10px] text-white"
        >
          <option value="0.5">0.5×</option>
          <option value="1">1×</option>
          <option value="2">2×</option>
        </select>

        <div className="ml-auto flex items-center gap-1">
          <Zap className="h-3 w-3 text-[#00E5FF]" />
          <span className="text-xs text-[#a1a1aa]">
            {camCount ? `${onAir ?? 'No program angle'} · ${camCount} ${camCount === 1 ? 'camera' : 'cameras'}` : 'No camera media'}
          </span>
        </div>
      </div>
    </div>
  );
}