import { useEffect, useState } from 'react';
import { useStore } from '@/store/useStore';
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react';

export default function JobStatusPanel() {
  const pipeline = useStore((s) => s.pipeline);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Start timer when pipeline starts
  useEffect(() => {
    if (pipeline.stage !== 'idle' && pipeline.stage !== 'ready' && pipeline.stage !== 'failed') {
      if (!startTime) setStartTime(Date.now());
    } else {
      setStartTime(null);
      setElapsed(0);
    }
  }, [pipeline.stage, startTime]);

  // Update elapsed time every second
  useEffect(() => {
    if (!startTime) return;
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  // Calculate ETA based on progress percentage
  const calculateETA = () => {
    if (!pipeline.percentage || pipeline.percentage === 0 || !startTime) return null;
    const totalEstimatedTime = (elapsed / pipeline.percentage) * 100;
    const remaining = Math.max(0, totalEstimatedTime - elapsed);
    return remaining;
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
  };

  const eta = calculateETA();

  return (
    <div className="rounded-xl border border-[#2a2a32] bg-[#141418] p-4 space-y-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        {pipeline.stage === 'ready' ? (
          <CheckCircle2 className="text-emerald-400" size={16} />
        ) : pipeline.stage === 'failed' ? (
          <AlertCircle className="text-rose-400" size={16} />
        ) : (
          <Loader2 className="text-[#00E5FF] animate-spin" size={16} />
        )}
        <span className="text-white capitalize">{pipeline.stage.replace('_', ' ')}</span>
        <span className="ml-auto text-[#00E5FF] font-mono">{Math.round(pipeline.percentage || 0)}%</span>
      </div>

      <div className="h-1.5 w-full bg-[#2a2a32] rounded-full overflow-hidden">
        <div
          className="h-full bg-[#00E5FF] transition-all duration-300"
          style={{ width: `${pipeline.percentage || 0}%` }}
        />
      </div>

      {/* Real-time processing timers */}
      {(pipeline.stage !== 'idle' && pipeline.stage !== 'ready') && (
        <div className="flex items-center justify-between text-[11px] text-[#a1a1aa] pt-2 border-t border-[#2a2a32]">
          <div>
            Elapsed: <span className="text-white font-mono">{formatTime(elapsed)}</span>
          </div>
          {eta !== null && (
            <div>
              Remaining: <span className="text-[#00E5FF] font-mono">{formatTime(eta)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}