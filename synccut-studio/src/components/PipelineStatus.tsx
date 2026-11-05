import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  UploadCloud,
  Film,
  AudioWaveform,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Layers,
  AlertTriangle,
} from 'lucide-react';
import { useStore, PipelineStage } from '@/store/useStore';
import { cancelJob } from '@/lib/api';
import { toast } from 'sonner';

const STAGE_CONFIG: Record<
  PipelineStage,
  { label: string; icon: React.ElementType; color: string }
> = {
  idle: {
    label: 'Drop clips to begin auto sync',
    icon: UploadCloud,
    color: 'text-[#71717a]',
  },
  uploading: {
    label: 'Uploading your camera files...',
    icon: UploadCloud,
    color: 'text-[#00E5FF]',
  },
  proxying: {
    label: 'Building preview proxies...',
    icon: Film,
    color: 'text-[#00E5FF]',
  },
  syncing: {
    label: 'Aligning audio across cameras...',
    icon: AudioWaveform,
    color: 'text-[#00E5FF]',
  },
  ai_cutting: {
    label: 'Detecting speaker cuts...',
    icon: Sparkles,
    color: 'text-[#00E5FF]',
  },
  ready: {
    label: '✓ Timeline ready to export',
    icon: CheckCircle2,
    color: 'text-emerald-400',
  },
  failed: {
    label: 'Something went wrong — try again',
    icon: AlertCircle,
    color: 'text-rose-400',
  },
};

export const PipelineStatus: React.FC = () => {
  const pipeline = useStore((s) => s.pipeline);
  const segments = useStore((s) => s.segments);
  const jobId = useStore((s) => s.jobId);
  const syncStartedAt = useStore((s) => s.syncStartedAt);
  const [now, setNow] = useState(Date.now());
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const progressSample = useRef<{ percentage: number; at: number } | null>(null);

  useEffect(() => {
    if (!syncStartedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [syncStartedAt]);

  const stage = pipeline.stage;
  const percentage = pipeline.percentage;
  const jobStatus = pipeline.jobStatus;
  useEffect(() => {
    if (
      percentage === null ||
      percentage <= 0 ||
      percentage >= 99 ||
      jobStatus === 'STALLED' ||
      jobStatus === 'UNKNOWN' ||
      stage === 'ready' ||
      stage === 'failed'
    ) {
      progressSample.current = percentage === null
        ? null
        : { percentage, at: Date.now() };
      setEtaSeconds(null);
      return;
    }

    const nowAt = Date.now();
    const previous = progressSample.current;
    if (
      previous &&
      percentage > previous.percentage &&
      nowAt - previous.at >= 5000
    ) {
      const progressPerSecond = (percentage - previous.percentage) / ((nowAt - previous.at) / 1000);
      if (progressPerSecond > 0) {
        setEtaSeconds(Math.ceil((100 - percentage) / progressPerSecond));
      }
      progressSample.current = { percentage, at: nowAt };
    } else if (!previous || percentage < previous.percentage) {
      progressSample.current = { percentage, at: nowAt };
    }
  }, [percentage, jobStatus, stage]);

  const config = STAGE_CONFIG[stage] || STAGE_CONFIG.idle;
  const Icon = config.icon;
  const elapsedSeconds = syncStartedAt
    ? Math.max(0, Math.floor((now - syncStartedAt) / 1000))
    : null;
  const formatDuration = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    if (minutes > 0) {
      return `${minutes}m ${remainingSeconds}s`;
    }
    return `${remainingSeconds}s`;
  };

  const isWorking = stage !== 'idle' && stage !== 'ready' && stage !== 'failed';

  return (
    <div className="rounded-xl border border-[#2a2a32] bg-[#121217] p-3.5 space-y-3 shadow-lg">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isWorking ? (
            <Loader2 className="h-4 w-4 animate-spin text-[#00E5FF]" />
          ) : (
            <Icon className={`h-4 w-4 ${config.color}`} />
          )}
          <span className="text-xs font-semibold text-white tracking-wide uppercase">
            Auto Sync
          </span>
        </div>

        {jobStatus === 'STALLED' ? (
          <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-400">
            <AlertTriangle size={13} /> Stalled
          </span>
        ) : jobStatus === 'UNKNOWN' ? (
          <span className="text-xs font-bold text-amber-400">Status unavailable</span>
        ) : percentage === null ? (
          <span className="text-xs font-bold text-[#00E5FF]">working</span>
        ) : <span
          className={`font-mono text-xs font-bold ${
            stage === 'ready'
              ? 'text-emerald-400'
              : stage === 'failed'
              ? 'text-rose-400'
              : 'text-[#00E5FF]'
          }`}
        >
          {stage === 'ready' ? 'Complete' : stage === 'failed' ? 'Failed' : stage === 'idle' ? 'Ready' : 'working'}
        </span>}
      </div>

      {/* Glowing Cyan Animated Progress Bar */}
      <div className="relative w-full bg-[#1e1e26] h-2 rounded-full overflow-hidden">
        {percentage === null ? (
          jobStatus !== 'UNKNOWN' && (
            <motion.div
              initial={{ x: '-35%' }}
              animate={{ x: '300%' }}
              transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
              className={`absolute h-full w-1/3 rounded-full ${jobStatus === 'STALLED' ? 'bg-amber-400' : 'bg-[#00E5FF]'}`}
            />
          )
        ) : <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.max(0, percentage)}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className={`h-full transition-all duration-300 ${
            stage === 'ready'
              ? 'bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.6)]'
              : stage === 'failed'
              ? 'bg-rose-500'
              : 'bg-[#00E5FF] shadow-[0_0_15px_rgba(0,229,255,0.7)]'
          }`}
        />}
      </div>

      {/* Status Message / Microcopy */}
      <div className="flex items-center justify-between text-[11px] text-[#a1a1aa] pt-0.5">
        <span className="truncate max-w-[210px] font-medium text-white">
          {pipeline.message || config.label}
        </span>
        {elapsedSeconds !== null && (
          <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[10px] text-[#a1a1aa]">
            <Clock className="h-3 w-3" />
            {stage === 'ready' ? 'Finished' : `Elapsed ${formatDuration(elapsedSeconds)}`}
            {stage === 'ready'
              ? ' · 0s remaining'
              : jobStatus === 'STALLED'
              ? ' · estimate paused'
              : jobStatus === 'UNKNOWN'
              ? ' · estimate unavailable'
              : etaSeconds !== null
              ? ` · ~${formatDuration(etaSeconds)} remaining`
              : isWorking
              ? ' · estimating remaining'
              : ''}
          </span>
        )}
      </div>
      {jobStatus === 'STALLED' && jobId && (
        <button
          className="rounded border border-amber-500/40 px-2 py-1 text-xs text-amber-300 hover:bg-amber-500/10"
          onClick={() => cancelJob(jobId).then(() => toast.info('Cancellation requested.')).catch(() => toast.error('Could not cancel this job.'))}
        >
          Stop job
        </button>
      )}

      {/* Review Info Tag */}
      {stage === 'ready' && (
        <div className="pt-2 border-t border-white/5 flex items-center justify-between text-[11px] text-[#71717a]">
          <span className="flex items-center gap-1 text-[#ededed]">
            <Layers className="h-3 w-3 text-[#00E5FF]" />
            {segments.length} Program Cuts
          </span>
          <span className="text-emerald-400 font-medium">Unlocked</span>
        </div>
      )}
    </div>
  );
};
