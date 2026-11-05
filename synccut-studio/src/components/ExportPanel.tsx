import { useState } from 'react';
import { Clapperboard, FileCode2, FileText, Loader2, Film } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { exportTimeline } from '@/lib/api';
import { useStore } from '@/store/useStore';

// NOTE: "fcpxml" is in your contract; "aaf" and "audit_pdf" are assumed format keys. Rename to match Flask.
const EXPORTS = [
  { key: 'fcpxml', label: 'Export FCPXML', ext: 'fcpxml', Icon: FileCode2 },
  { key: 'edl', label: 'Export EDL', ext: 'edl', Icon: Film },
  { key: 'aaf', label: 'Export AAF', ext: 'aaf', Icon: Clapperboard },
  { key: 'audit_pdf', label: 'Download Sync Audit (PDF)', ext: 'pdf', Icon: FileText },
] as const;

export default function ExportPanel() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, ext: string) => {
    const { sessionId, manualOverrides, toProjectFile } = useStore.getState();
    setBusy(key);
    setError(null);
    try {
      const { blob, filename } = await exportTimeline(
        sessionId,
        key,
        toProjectFile(),
        manualOverrides,
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename ?? `synccut-${sessionId.slice(0, 8)}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (caught: any) {
      setError(caught?.response?.data?.error ?? caught?.message ?? 'Export failed.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Export</h3>
      {EXPORTS.map(({ key, label, ext, Icon }) => (
        <Button key={key} variant="outline" className="w-full justify-start" disabled={!!busy} onClick={() => run(key, ext)}>
          {busy === key ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
          {label}
        </Button>
      ))}
      {error && <p className="text-xs text-[#EF4444]">{error}</p>}
    </div>
  );
}
