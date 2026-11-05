import React, { useRef, useState, useEffect } from 'react';
import { useStore } from '@/store/useStore';
import { formatTC } from '@/lib/utils';
import {
  Scissors,
  Split,
  Eye,
  Volume2,
  Lock,
  Layers,
  ZoomIn,
  ZoomOut,
  Sparkles,
  ChevronRight,
  Clock,
  Play,
  Pause,
  SkipBack,
  Video,
  Music,
  HelpCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export default function CapCutTimeline() {
  const containerRef = useRef<HTMLDivElement>(null);
  const trackAreaRef = useRef<HTMLDivElement>(null);

  const duration = useStore((s) => s.duration) || 60;
  const currentTime = useStore((s) => s.currentTime);
  const setCurrentTime = useStore((s) => s.setCurrentTime);
  const isPlaying = useStore((s) => s.isPlaying);
  const togglePlay = useStore((s) => s.togglePlay);

  const segments = useStore((s) => s.segments);
  const overrides = useStore((s) => s.manualOverrides);
  const setOverride = useStore((s) => s.setOverride);
  const clearOverride = useStore((s) => s.clearOverride);
  const files = useStore((s) => s.files);
  const pipeline = useStore((s) => s.pipeline);

  const isLocked = pipeline.stage !== 'ready' && pipeline.stage !== 'idle';

  const [zoom, setZoom] = useState(1);
  const [menuTime, setMenuTime] = useState(0);
  const [isDraggingPlayhead, setIsDraggingPlayhead] = useState(false);

  // Time ticks calculation (e.g. 5s / 10s intervals)
  const step = duration > 120 ? 15 : duration > 60 ? 10 : 5;
  const timeMarkers = [];
  for (let t = 0; t <= duration; t += step) {
    timeMarkers.push(t);
  }

  // Handle Scrubbing
  const handleScrub = (clientX: number) => {
    if (isLocked) return;
    if (!trackAreaRef.current || duration <= 0) return;
    const rect = trackAreaRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    const newTime = Math.min((x / rect.width) * duration, duration);
    setCurrentTime(Math.round(newTime * 100) / 100);
  };

  const onMouseDownTrack = (e: React.MouseEvent) => {
    if (isLocked) return;
    setIsDraggingPlayhead(true);
    handleScrub(e.clientX);
  };

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isDraggingPlayhead && !isLocked) {
        handleScrub(e.clientX);
      }
    };
    const onMouseUp = () => {
      if (isDraggingPlayhead) {
        setIsDraggingPlayhead(false);
      }
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isDraggingPlayhead, isLocked, duration]);

  // Context menu positioning
  const handleContextMenu = (e: React.MouseEvent) => {
    if (isLocked || !trackAreaRef.current) return;
    const rect = trackAreaRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const t = Math.min((x / rect.width) * duration, duration);
    setMenuTime(Math.round(t * 100) / 100);
  };

  const playheadPercent = duration > 0 ? (currentTime / duration) * 100 : 0;
  const existingOverride = overrides[menuTime];

  return (
    <TooltipProvider>
      <div className={`flex h-full flex-col bg-[#0e0e12] select-none border-t border-[#22222b] ${isLocked ? 'opacity-50 pointer-events-none' : ''}`}>
        {/* 1. CapCut Editing Action Toolbar */}
        <div className="flex h-10 shrink-0 items-center justify-between border-b border-[#22222b] bg-[#141418] px-3">
          {/* Left: Standard NLE Toolset */}
          <div className="flex items-center gap-1 sm:gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setCurrentTime(0)}
              disabled={isLocked}
              className="h-7 px-2 text-[#a1a1aa] hover:text-[#00E5FF] hover:bg-white/5"
              title="Go to Start (Home)"
            >
              <SkipBack className="h-3.5 w-3.5" />
            </Button>

            <Button
              size="sm"
              onClick={togglePlay}
              disabled={isLocked}
              className="h-7 px-2.5 bg-[#00E5FF] text-[#04181c] hover:bg-[#33ecff] font-semibold text-xs"
              title="Play/Pause (Space)"
            >
              {isPlaying ? <Pause className="h-3.5 w-3.5 mr-1" /> : <Play className="h-3.5 w-3.5 mr-1" />}
              {isPlaying ? 'Pause' : 'Play'}
            </Button>

            <div className="h-4 w-px bg-white/10 mx-1" />

            {/* Timecode display */}
            <div className="flex items-center gap-1.5 font-mono text-xs text-[#00E5FF] bg-black/40 px-2 py-0.5 rounded border border-[#2a2a32]">
              <Clock className="h-3 w-3 text-[#71717a]" />
              <span>{formatTC(currentTime)}</span>
              <span className="text-[#71717a]">/</span>
              <span className="text-[#a1a1aa]">{formatTC(duration)}</span>
            </div>

            <div className="h-4 w-px bg-white/10 mx-1" />

            {/* Split / Switch Tools */}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOverride(currentTime, 'Camera A')}
              disabled={isLocked}
              className="h-7 px-2 text-xs text-[#a1a1aa] hover:text-[#00E5FF] hover:bg-white/5"
              title="Switch Active Angle to Cam A at playhead"
            >
              <Scissors className="h-3.5 w-3.5 mr-1 text-[#00E5FF]" />
              Cut Cam A
            </Button>

            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOverride(currentTime, 'Camera B')}
              disabled={isLocked}
              className="h-7 px-2 text-xs text-[#a1a1aa] hover:text-emerald-400 hover:bg-white/5"
              title="Switch Active Angle to Cam B at playhead"
            >
              <Scissors className="h-3.5 w-3.5 mr-1 text-emerald-400" />
              Cut Cam B
            </Button>
          </div>

          {/* Right: Deliverable 4 Tooltip on timeline override */}
          <div className="flex items-center gap-3 text-xs text-[#a1a1aa]">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1 text-[11px] text-[#71717a] hover:text-[#00E5FF] cursor-help">
                  <HelpCircle className="h-3.5 w-3.5" />
                  <span>Manual Overrides</span>
                </div>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs bg-[#16161e] border-[#2a2a32] text-white text-xs p-2.5">
                Click anywhere to override the AI camera choice. Your manual cuts will be saved in the final XML.
              </TooltipContent>
            </Tooltip>

            <div className="flex items-center gap-1 bg-[#1a1a22] rounded p-0.5 border border-[#2a2a32]">
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setZoom((z) => Math.max(0.6, z - 0.2))}
                className="h-6 w-6 text-[#a1a1aa] hover:text-white"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </Button>
              <span className="text-[10px] font-mono px-1">{zoom.toFixed(1)}x</span>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setZoom((z) => Math.min(2.5, z + 0.2))}
                className="h-6 w-6 text-[#a1a1aa] hover:text-white"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>

        {/* 2. Main Multi-Track CapCut Timeline Container */}
        <div className="flex flex-1 min-h-0 overflow-x-auto overflow-y-hidden" ref={containerRef}>
          {/* Track Headers */}
          <div className="w-44 shrink-0 flex flex-col border-r border-[#22222b] bg-[#111116] z-20 shadow-md">
            <div className="h-6 border-b border-[#22222b] bg-[#16161e] px-2 flex items-center text-[10px] font-semibold text-[#71717a] uppercase tracking-wider">
              <span>Layers & Tracks</span>
            </div>

            {/* Track 1: Master Program Cut */}
            <div className="h-14 border-b border-[#22222b] px-2.5 py-1.5 flex flex-col justify-between bg-[#13131a]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-[#00E5FF] flex items-center gap-1">
                  <Layers className="h-3.5 w-3.5" />
                  V1: Master Cut
                </span>
                <span className="text-[10px] font-mono text-emerald-400">ON AIR</span>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-[#71717a]">
                <span>{pipeline.stage === 'ready' ? 'AI Switches Active' : 'Auto-Cutting Speakers...'}</span>
              </div>
            </div>

            {/* Track 2: Camera A (Host) */}
            <div className="h-14 border-b border-[#22222b] px-2.5 py-1.5 flex flex-col justify-between hover:bg-white/[0.02]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white flex items-center gap-1">
                  <Video className="h-3.5 w-3.5 text-[#00E5FF]" />
                  Cam A (Host)
                </span>
                <Eye className="h-3 w-3 text-[#71717a]" />
              </div>
              <span className="text-[10px] text-[#71717a] truncate font-mono">
                {files[0]?.name || 'cam1_host.mp4'}
              </span>
            </div>

            {/* Track 3: Camera B (Guest) */}
            <div className="h-14 border-b border-[#22222b] px-2.5 py-1.5 flex flex-col justify-between hover:bg-white/[0.02]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-white flex items-center gap-1">
                  <Video className="h-3.5 w-3.5 text-emerald-400" />
                  Cam B (Guest)
                </span>
                <Eye className="h-3 w-3 text-[#71717a]" />
              </div>
              <span className="text-[10px] text-[#71717a] truncate font-mono">
                {files[1]?.name || 'cam2_guest.mp4'}
              </span>
            </div>

            {/* Track 4: Audio Waveform Stem (A1) */}
            <div className="h-14 px-2.5 py-1.5 flex flex-col justify-between hover:bg-white/[0.02]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#a1a1aa] flex items-center gap-1">
                  <Volume2 className="h-3.5 w-3.5 text-amber-400" />
                  A1: Master Stem
                </span>
                <span className="text-[10px] font-mono text-[#71717a]">48kHz 24b</span>
              </div>
              <span className="text-[10px] text-[#71717a]">
                {pipeline.stage === 'ready' ? 'Sub-frame Sync Match' : 'Aligning Audio...'}
              </span>
            </div>
          </div>

          {/* Tracks Content Area with CapCut Layer Bars & Playhead */}
          <div
            ref={trackAreaRef}
            onMouseDown={onMouseDownTrack}
            onContextMenu={handleContextMenu}
            className="relative flex-1 min-w-[700px] bg-[#0c0c10] cursor-pointer overflow-hidden"
            style={{ width: `${zoom * 100}%` }}
          >
            {/* Time Ruler */}
            <div className="h-6 border-b border-[#22222b] bg-[#121218] relative">
              {timeMarkers.map((time) => {
                const leftPercent = duration > 0 ? (time / duration) * 100 : 0;
                return (
                  <div
                    key={time}
                    className="absolute top-0 bottom-0 flex flex-col justify-between"
                    style={{ left: `${leftPercent}%` }}
                  >
                    <span className="text-[9px] font-mono text-[#71717a] pl-1 -translate-x-1/2">
                      {formatTC(time).slice(3, 8)}
                    </span>
                    <div className="h-1.5 w-px bg-[#3a3a46]" />
                  </div>
                );
              })}
            </div>

            {/* Context Menu Trigger for Timeline Overrides */}
            <ContextMenu>
              <ContextMenuTrigger asChild>
                <div className="relative w-full h-[calc(100%-24px)]">
                  {/* TRACK 1: Master Program Cut */}
                  <div className="h-14 border-b border-[#22222b]/60 relative px-1 py-1 flex items-center">
                    {segments.length > 0 ? (
                      segments.map((seg, idx) => {
                        const isCamA = seg.camera.toLowerCase().includes('a') || seg.camera.includes('1');
                        const startPct = (seg.start / duration) * 100;
                        const widthPct = ((seg.end - seg.start) / duration) * 100;

                        return (
                          <div
                            key={idx}
                            style={{ left: `${startPct}%`, width: `${widthPct}%` }}
                            className={`absolute top-1 bottom-1 rounded border overflow-hidden flex items-center justify-between px-2 text-[10px] font-semibold transition-all ${
                              isCamA
                                ? 'bg-[#00E5FF]/20 border-[#00E5FF]/60 text-[#00E5FF] hover:bg-[#00E5FF]/30'
                                : 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300 hover:bg-emerald-500/30'
                            }`}
                          >
                            <span className="truncate">{seg.camera}</span>
                            <span className="font-mono text-[9px] opacity-75">
                              {Math.round((seg.end - seg.start) * 10) / 10}s
                            </span>
                          </div>
                        );
                      })
                    ) : (
                      <div className="w-full h-full rounded border border-[#00E5FF]/40 bg-[#00E5FF]/15 px-3 flex items-center justify-between text-xs text-[#00E5FF]">
                        <span>Camera A (Master)</span>
                        <span className="text-[10px] text-[#a1a1aa]">Continuous Take</span>
                      </div>
                    )}

                    {/* Manual Overrides Display */}
                    {Object.entries(overrides).map(([timeStr, cam]) => {
                      const t = Number(timeStr);
                      const leftPct = (t / duration) * 100;
                      return (
                        <div
                          key={timeStr}
                          style={{ left: `${leftPct}%` }}
                          className="absolute top-0 bottom-0 w-2 z-10 flex flex-col items-center justify-center -translate-x-1/2"
                        >
                          <div className="h-full w-0.5 bg-[#00E5FF] shadow-[0_0_8px_#00E5FF]" />
                          <span className="absolute top-0.5 bg-[#00E5FF] text-[#04181c] text-[8px] font-bold px-1 rounded">
                            {cam.slice(-1)}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  {/* TRACK 2: Camera A Raw Clip Layer */}
                  <div className="h-14 border-b border-[#22222b]/60 relative px-1 py-1 flex items-center">
                    <div className="w-full h-full rounded-md border border-[#2a2a38] bg-[#191924] px-3 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs text-white">
                        <div className="h-2 w-2 rounded-full bg-[#00E5FF]" />
                        <span className="font-medium">Camera A (Host Wide)</span>
                        <span className="text-[10px] font-mono text-[#71717a]">[4K 24fps]</span>
                      </div>
                      <div className="flex items-center gap-1 opacity-25">
                        {Array.from({ length: 16 }).map((_, i) => (
                          <div key={i} className="h-4 w-6 rounded-sm border border-white/20 bg-white/5" />
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* TRACK 3: Camera B Raw Clip Layer */}
                  <div className="h-14 border-b border-[#22222b]/60 relative px-1 py-1 flex items-center">
                    <div className="w-full h-full rounded-md border border-[#2a2a38] bg-[#161c20] px-3 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs text-white">
                        <div className="h-2 w-2 rounded-full bg-emerald-400" />
                        <span className="font-medium">Camera B (Guest Close-up)</span>
                        <span className="text-[10px] font-mono text-[#71717a]">[4K 24fps]</span>
                      </div>
                      <div className="flex items-center gap-1 opacity-25">
                        {Array.from({ length: 16 }).map((_, i) => (
                          <div key={i} className="h-4 w-6 rounded-sm border border-white/20 bg-white/5" />
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* TRACK 4: Waveform Stem Layer */}
                  <div className="h-14 relative px-1 py-1 flex items-center">
                    <div className="w-full h-full rounded-md border border-amber-500/20 bg-amber-500/5 px-3 flex items-center justify-between overflow-hidden">
                      <div className="w-full h-8 flex items-center gap-0.5 opacity-80">
                        {Array.from({ length: 120 }).map((_, i) => {
                          const h = Math.sin(i * 0.25) * 40 + Math.cos(i * 0.8) * 35 + 25;
                          return (
                            <div
                              key={i}
                              className="flex-1 rounded-sm bg-gradient-to-t from-amber-500/40 via-amber-400 to-amber-300"
                              style={{ height: `${Math.max(12, Math.min(100, Math.abs(h)))}%` }}
                            />
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              </ContextMenuTrigger>

              {/* Right Click Menu */}
              <ContextMenuContent className="border-[#2a2a32] bg-[#141418] text-[#ededed]">
                <ContextMenuLabel className="text-xs text-[#a1a1aa]">
                  At {formatTC(menuTime)}
                </ContextMenuLabel>
                <ContextMenuItem
                  onClick={() => setOverride(menuTime, 'Camera A')}
                  className="cursor-pointer text-xs"
                >
                  <Scissors className="h-3.5 w-3.5 mr-2 text-[#00E5FF]" />
                  Cut & Switch to Camera A
                </ContextMenuItem>
                <ContextMenuItem
                  onClick={() => setOverride(menuTime, 'Camera B')}
                  className="cursor-pointer text-xs"
                >
                  <Scissors className="h-3.5 w-3.5 mr-2 text-emerald-400" />
                  Cut & Switch to Camera B
                </ContextMenuItem>
                {existingOverride && (
                  <>
                    <ContextMenuSeparator />
                    <ContextMenuItem
                      onClick={() => clearOverride(menuTime)}
                      className="cursor-pointer text-xs text-rose-400"
                    >
                      Remove Cut ({existingOverride})
                    </ContextMenuItem>
                  </>
                )}
              </ContextMenuContent>
            </ContextMenu>

            {/* Playhead Needle */}
            <div
              style={{ left: `${playheadPercent}%` }}
              className="absolute top-0 bottom-0 z-30 pointer-events-none -translate-x-1/2 flex flex-col items-center"
            >
              <div className="w-3.5 h-3.5 bg-[#00E5FF] shadow-[0_0_12px_#00E5FF] rotate-45 transform -translate-y-1 rounded-sm" />
              <div className="w-0.5 flex-1 bg-[#00E5FF] shadow-[0_0_8px_rgba(0,229,255,0.8)]" />
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
