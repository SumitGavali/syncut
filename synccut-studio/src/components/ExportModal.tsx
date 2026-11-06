import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { FileCode2, Clapperboard, FileText, Download, Loader2, Film } from 'lucide-react';
import { exportTimeline } from '@/lib/api';
import { useStore } from '@/store/useStore';
import { useEditorStore } from '@/store/useEditorStore'; // <-- IMPORT ADDED
import { useAuthStore } from '@/store/useAuthStore';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

interface ExportModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface ExportFormatOption {
  id: string;
  key: string;
  ext: string;
  name: string;
  subtitle: string;
  icon: React.ElementType;
  proOnly?: boolean;
}

const FORMAT_OPTIONS: ExportFormatOption[] = [
  {
    id: 'fcpxml',
    key: 'fcpxml',
    ext: 'fcpxml',
    name: 'FCPXML (Final Cut Pro / Premiere)',
    subtitle: 'Includes multicam sync offsets, clip markers & manual NLE edits',
    icon: FileCode2,
    proOnly: true,
  },
  {
    id: 'edl',
    key: 'edl',
    ext: 'edl',
    name: 'EDL (Edit Decision List)',
    subtitle: 'Camera sync lanes and the edited program lane',
    icon: Film,
  },
  {
    id: 'aaf',
    key: 'aaf',
    ext: 'aaf',
    name: 'AAF (Avid Media Composer / Pro Tools)',
    subtitle: 'Sync offsets, camera lanes, and the edited program lane',
    icon: Clapperboard,
    proOnly: true,
  },
  {
    id: 'audit_pdf',
    key: 'audit_pdf',
    ext: 'pdf',
    name: 'Sync Audit Report (PDF)',
    subtitle: 'Measured offsets, drift, pairwise consistency, and program edits',
    icon: FileText,
  },
];

export const ExportModal: React.FC<ExportModalProps> = ({ open, onOpenChange }) => {
  const tier = useAuthStore((state) => state.user?.tier ?? 'free');
  const navigate = useNavigate();
  const [selectedFormats, setSelectedFormats] = useState<string[]>([
    tier === 'free' ? 'edl' : 'fcpxml',
  ]);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadStep, setDownloadStep] = useState<string | null>(null);
  const [confirmWeak, setConfirmWeak] = useState(false);
  const syncData = useStore((state) => state.syncData);
  const lockedCount = syncData.filter((camera) => camera.state === 'LOCKED').length;
  const verifyCount = syncData.filter((camera) => camera.state === 'VERIFY').length;
  const weakCount = syncData.filter((camera) => camera.state === 'WEAK' || !camera.state).length;
  const needsReview = verifyCount + weakCount > 0;

  useEffect(() => {
    if (!open) setConfirmWeak(false);
  }, [open]);

  useEffect(() => {
    if (tier === 'free') {
      setSelectedFormats((formats) => {
        const available = formats.filter((format) => format !== 'fcpxml' && format !== 'aaf');
        return available.length ? available : ['edl'];
      });
    }
  }, [tier]);

  const toggleFormat = (id: string) => {
    const option = FORMAT_OPTIONS.find((format) => format.id === id);
    if (tier === 'free' && option?.proOnly) {
      navigate('/pricing');
      return;
    }
    setSelectedFormats((prev) =>
      prev.includes(id)
        ? prev.length > 1
          ? prev.filter((item) => item !== id)
          : prev
        : [...prev, id]
    );
  };

  const handleDownload = async () => {
    const { sessionId, manualOverrides, pipeline, toProjectFile } = useStore.getState();
    // GRAB THE EXACT NLE STATE
    const { clips } = useEditorStore.getState();

    if (pipeline.stage !== 'ready') {
      toast.error('Sync in progress. Export will unlock once AI cuts are finalized.');
      return;
    }
    if (needsReview && !confirmWeak) {
      setConfirmWeak(true);
      return;
    }

    setIsDownloading(true);

    try {
      for (const formatId of selectedFormats) {
        const option = FORMAT_OPTIONS.find((f) => f.id === formatId);
        if (!option) continue;

        setDownloadStep(`Packaging ${option.name}...`);
        
        // PASS CLIPS TO BACKEND
        const { blob, filename } = await exportTimeline(
          sessionId,
          option.key,
          toProjectFile(),
          manualOverrides,
          clips // <-- THIS IS THE NEW ARGUMENT
        );

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename ?? `synccut-${sessionId.slice(0, 8)}.${option.ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }

      toast.success('Timeline exported with measured offsets and program edits.');
      onOpenChange(false);
    } catch (err: any) {
      const status = err?.response?.status;
      if (status === 400) {
        toast.error('Export is not ready yet. Wait for synchronization to finish.');
      } else {
        toast.error('Export failed. Please try again.');
      }
    } finally {
      setIsDownloading(false);
      setDownloadStep(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] border border-[#2a2a32] bg-[#121216] text-[#ededed] shadow-2xl">
        <DialogHeader className="space-y-1.5">
          <DialogTitle className="text-lg font-bold text-white flex items-center gap-2">
            <Download className="h-5 w-5 text-[#00E5FF]" />
            Save & Export Timeline Package
          </DialogTitle>
          <DialogDescription className="text-xs text-[#a1a1aa]">
            Select target NLE formats. Measured offsets and the edited program lane are included.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs">
          <div className="font-semibold text-white">
            {lockedCount} LOCKED, {verifyCount} VERIFY, {weakCount} WEAK
          </div>
          {needsReview && (
            <p className="mt-1 text-amber-300">
              Some cameras need review. Click Export anyway to continue with the measured values.
            </p>
          )}
        </div>

        <div className="my-4 space-y-3">
          {FORMAT_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const isChecked = selectedFormats.includes(opt.id);
            const requiresPro = tier === 'free' && opt.proOnly;

            return (
              <div
                key={opt.id}
                onClick={() => toggleFormat(opt.id)}
                className={`flex items-start gap-3.5 rounded-xl border p-3.5 cursor-pointer transition-all ${
                  isChecked
                    ? 'border-[#00E5FF]/40 bg-[#00E5FF]/5 shadow-[0_0_15px_rgba(0,229,255,0.06)]'
                    : 'border-[#2a2a32] bg-[#16161d] hover:border-white/20'
                }`}
              >
                <Checkbox
                  checked={isChecked}
                  onCheckedChange={() => toggleFormat(opt.id)}
                  disabled={requiresPro}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <Icon className={`h-4 w-4 ${isChecked ? 'text-[#00E5FF]' : 'text-[#71717a]'}`} />
                    <span className="text-sm font-semibold text-white">{opt.name}</span>
                    {requiresPro && (
                      <span className="rounded border border-[#00E5FF]/30 px-1.5 py-0.5 text-[10px] text-[#00E5FF]">
                        PRO
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-[#a1a1aa] leading-relaxed">
                    {opt.subtitle}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
        {tier === 'free' && (
          <p className="-mt-2 text-xs text-[#a1a1aa]">
            <button
              type="button"
              onClick={() => navigate('/pricing')}
              className="font-semibold text-[#00E5FF] hover:underline"
            >
              Upgrade to Pro
            </button>{' '}
            to unlock FCPXML and AAF exports.
          </p>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isDownloading}
            className="text-[#a1a1aa] hover:text-white"
          >
            Cancel
          </Button>

          <Button
            onClick={handleDownload}
            disabled={selectedFormats.length === 0 || isDownloading}
            className="bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.25)] min-w-[140px]"
          >
            {isDownloading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                <span>{downloadStep || 'Exporting...'}</span>
              </>
            ) : (
              <>
                <Download className="h-4 w-4 mr-2" />
                <span>{confirmWeak ? 'Export anyway' : `Download (${selectedFormats.length})`}</span>
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};