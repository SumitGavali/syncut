import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AudioLines, ChevronDown, CircleHelp, Clapperboard, Download, FilePlus2, Film,
  FolderOpen, Gauge, Music2, Redo2, Save, Undo2, WandSparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import ProgramMonitor from '@/components/ProgramMonitor';
import Timeline from '@/components/Timeline';
import OnboardingTour from '@/components/OnboardingTour';
import { ExportModal } from '@/components/ExportModal';
import { Button } from '@/components/ui/button';
import { useProjectStore } from '@/store/useProjectStore';
import { useStore, type CameraSync, type PipelineStage, type Segment } from '@/store/useStore';
import { useEditorStore, type EditorClip } from '@/store/useEditorStore';
import { getJobStatus, getSessionMediaUrl, loadSessionProject, saveSessionProject, uploadFiles } from '@/lib/api';

const CAMERA_COLORS = ['#06b6d4', '#a855f7', '#f97316', '#ec4899', '#22c55e', '#eab308', '#3b82f6', '#14b8a6'];
const MEDIA_ACCEPT = 'video/*,audio/*,.mp4,.mov,.m4v,.mkv,.avi,.webm,.mts,.m2ts,.ts,.mpg,.mpeg,.3gp,.wmv,.mp3,.wav,.m4a,.aac,.flac,.ogg';

type MediaTab = 'Media' | 'Audio' | 'Effects';
type InspectorTab = 'Inspector' | 'Metadata';

function formatDuration(seconds: number) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remaining).padStart(2, '0')}`;
}

function buildProgramDraft(suggestions: Segment[], cameras: CameraSync[]): Segment[] {
  const endTime = Math.max(0, ...cameras.map((camera) => Number(camera.offset_s ?? 0) + Number(camera.duration_sec ?? 0)));
  if (!Number.isFinite(endTime) || endTime <= 0 || !cameras.length) return [];

  const validSuggestions = suggestions.filter((segment) =>
    cameras.some((camera) => camera.source === segment.camera) &&
    Number.isFinite(segment.start) && Number.isFinite(segment.end) && segment.end > segment.start,
  );
  const boundaries = new Set<number>([0, endTime]);
  cameras.forEach((camera) => {
    const start = Number(camera.offset_s ?? 0);
    const end = start + Number(camera.duration_sec ?? 0);
    if (start > 0 && start < endTime) boundaries.add(start);
    if (end > 0 && end < endTime) boundaries.add(end);
  });
  validSuggestions.forEach((segment) => {
    const start = Math.max(0, Math.min(endTime, segment.start));
    const end = Math.max(0, Math.min(endTime, segment.end));
    if (start < end) { boundaries.add(start); boundaries.add(end); }
  });

  const sorted = [...boundaries].sort((a, b) => a - b);
  const master = cameras.find((camera) => camera.is_master) ?? cameras[0];
  const program: Segment[] = [];
  for (let index = 0; index < sorted.length - 1; index += 1) {
    const start = sorted[index];
    const end = sorted[index + 1];
    if (end - start < 0.001) continue;
    const midpoint = (start + end) / 2;
    const hasSource = (camera: CameraSync) => {
      const localTime = midpoint - Number(camera.offset_s ?? 0);
      return localTime >= 0 && localTime < Number(camera.duration_sec ?? 0);
    };
    const suggestion = validSuggestions.find((segment) => midpoint >= segment.start && midpoint < segment.end);
    const requested = suggestion && cameras.find((camera) => camera.source === suggestion.camera);
    const camera = requested && hasSource(requested) ? requested : hasSource(master) ? master : cameras.find(hasSource);
    if (!camera) continue;

    const previous = program[program.length - 1];
    if (previous?.camera === camera.source && Math.abs(previous.end - start) < 0.001) {
      previous.end = end;
      continue;
    }
    program.push({
      id: crypto.randomUUID(), camera: camera.source, start, end,
      confidence: suggestion?.confidence,
      reason: requested?.source === camera.source ? suggestion?.reason || 'AI camera selection' : 'Available synchronized source',
      source: 'suggested',
    });
  }
  return program;
}

function buildEditorClips(segments: Segment[], cameras: CameraSync[], sources: string[]): EditorClip[] {
  const cameraNames = cameras.map((camera) => camera.source);
  return segments.map((segment, index) => {
    const sourceIndex = Math.max(0, cameraNames.indexOf(segment.camera));
    const cameraIndex = cameraNames.indexOf(segment.camera);
    return {
      id: segment.id ?? `program-${index}-${segment.start.toFixed(3)}`,
      name: segment.camera, track: 0, start: segment.start,
      duration: Math.max(0.05, segment.end - segment.start),
      color: CAMERA_COLORS[(cameraIndex < 0 ? index : cameraIndex) % CAMERA_COLORS.length],
      confidence: segment.confidence, sourceIndex,
      sourceUrl: sources[sourceIndex], reason: segment.reason,
      scale: 100, positionX: 0, positionY: 0, rotation: 0, opacity: 100,
    };
  });
}

function MediaPool({ onImport, importing, fileInputRef }: { onImport: (files: File[]) => void; importing: boolean; fileInputRef: React.RefObject<HTMLInputElement>; }) {
  const [tab, setTab] = useState<MediaTab>('Media');
  const sources = useStore((state) => state.allSources);
  const files = useStore((state) => state.files);
  const cameras = useStore((state) => state.syncData);
  const duration = useStore((state) => state.duration);
  const selectedSourceIndex = useEditorStore((state) => state.selectedSourceIndex);
  const setSelectedSourceIndex = useEditorStore((state) => state.setSelectedSourceIndex);
  const setActiveClip = useEditorStore((state) => state.setActiveClip);
  const setPlayhead = useEditorStore((state) => state.setPlayhead);

  const rows = sources.map((source, index) => {
    const camera = cameras[index];
    const name = camera?.source || files[index]?.name?.replace(/\.[^.]+$/, '') || `Camera ${index + 1}`;
    const file = files[index];
    const type = file?.type || '';
    return {
      source, index, name,
      isAudio: type.startsWith('audio/') || /\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(file?.name ?? ''),
      duration: Number(camera?.duration_sec ?? duration),
    };
  }).filter((row) => tab === 'Audio' ? row.isAudio : tab === 'Media' ? !row.isAudio : false);

  return (
    <aside data-tour="media-pool" className="flex min-h-0 flex-col border-r border-border bg-panel">
      <div className="flex h-11 shrink-0 items-center border-b border-border px-2">
        {(['Media', 'Audio', 'Effects'] as const).map((item) => (
          <button key={item} type="button" onClick={() => setTab(item)} className={`relative h-full px-3 text-sm font-medium ${tab === item ? 'text-text' : 'text-muted hover:text-text'}`}>
            {item}
            {tab === item && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      <div className="p-3">
        <button type="button" onClick={() => fileInputRef.current?.click()} disabled={importing} data-tour="media-import" className="flex h-10 w-full items-center justify-center gap-2 rounded-md border border-accent/50 bg-accent/10 text-sm font-semibold text-accent transition hover:bg-accent/20 disabled:opacity-50">
          <FilePlus2 size={16} /> {importing ? 'Importing…' : 'Import Media'}
        </button>
        <input ref={fileInputRef} type="file" multiple accept={MEDIA_ACCEPT} onChange={(event) => { const selected = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ''; onImport(selected); }} className="hidden" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {tab === 'Effects' ? (
          <div className="mx-1 rounded-lg border border-border bg-background p-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-text"><WandSparkles size={15} className="text-accent" /> Effects</div>
            <p className="mt-2 text-xs leading-relaxed text-muted">Clip transitions, transform, and opacity controls are available in the Inspector.</p>
          </div>
        ) : rows.length ? (
          <div className="space-y-1">
            {rows.map((row) => (
              <button key={`${row.index}-${row.source}`} type="button" onClick={() => { setSelectedSourceIndex(row.index); setActiveClip(null); setPlayhead(0); }} className={`group flex w-full items-center gap-3 rounded-md border p-2 text-left transition ${selectedSourceIndex === row.index ? 'border-accent/40 bg-accent/10' : 'border-transparent hover:border-border hover:bg-panel'}`}>
                <div className="relative h-[56px] w-[84px] shrink-0 overflow-hidden rounded border border-white/10 bg-background">
                  {!row.isAudio && <video src={row.source} muted preload="metadata" onLoadedMetadata={(event) => { const video = event.currentTarget; if (video.duration > 0) video.currentTime = Math.min(0.1, video.duration / 2); }} className="h-full w-full object-cover" />}
                  {row.isAudio && <Music2 size={20} className="absolute inset-0 m-auto text-accent" />}
                  <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1 text-[10px] font-bold text-white">{String.fromCharCode(65 + row.index)}</span>
                </div>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-text">{row.name}</span>
                  <span className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
                    {row.isAudio ? <AudioLines size={12} /> : <Film size={12} />}
                    {formatDuration(row.duration)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="mx-1 mt-2 rounded-lg border border-dashed border-border bg-background px-3 py-5 text-center">
            <FolderOpen size={20} className="mx-auto text-muted" />
            <p className="mt-2 text-sm font-medium text-muted">{tab === 'Audio' ? 'No audio-only assets' : 'Your media will appear here'}</p>
            <p className="mt-1 text-[11px] text-muted/70">Import 2–8 camera files to create a synchronized project.</p>
          </div>
        )}
      </div>
      <div className="flex h-8 shrink-0 items-center justify-between border-t border-border px-3 text-[11px] text-muted">
        <span>{sources.length} assets</span>
        <span>{formatDuration(duration)} total</span>
      </div>
    </aside>
  );
}

function Inspector() {
  const [tab, setTab] = useState<InspectorTab>('Inspector');
  const clips = useEditorStore((state) => state.clips);
  const activeClipId = useEditorStore((state) => state.activeClipId);
  const setClipTransform = useEditorStore((state) => state.setClipTransform);
  const activeClip = clips.find((clip) => clip.id === activeClipId) ?? null;
  const cameras = useStore((state) => state.syncData);

  const slider = (label: string, value: number, min: number, max: number, step: number, key: 'scale' | 'positionX' | 'positionY' | 'rotation' | 'opacity', suffix = '') => (
    <label className="grid grid-cols-[64px_minmax(0,1fr)_48px] items-center gap-2">
      <span className="text-xs text-muted">{label}</span>
      <input aria-label={label} type="range" min={min} max={max} step={step} value={value} onChange={(event) => activeClip && setClipTransform(activeClip.id, key, Number(event.currentTarget.value))} disabled={!activeClip} className="h-1.5 w-full accent-accent disabled:opacity-40" />
      <span className="rounded border border-border bg-background px-1.5 py-1 text-center font-mono text-[11px] text-text">{value}{suffix}</span>
    </label>
  );

  return (
    <aside data-tour="inspector" className="flex min-h-0 flex-col border-l border-border bg-panel">
      <div className="flex h-11 shrink-0 items-center border-b border-border px-2">
        {(['Inspector', 'Metadata'] as const).map((item) => (
          <button key={item} type="button" onClick={() => setTab(item)} className={`relative h-full px-3 text-sm font-medium ${tab === item ? 'text-text' : 'text-muted hover:text-text'}`}>
            {item}
            {tab === item && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      {tab === 'Inspector' ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <section className="border-b border-border p-4">
            <div className="mb-3 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted">Selected Clip <ChevronDown size={14} /></div>
            {activeClip ? (
              <div className="flex items-center gap-3">
                <span className="h-3 w-3 rounded-full" style={{ backgroundColor: activeClip.color }} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-text">{activeClip.name}</p>
                  <p className="mt-1 font-mono text-[11px] text-muted">{formatDuration(activeClip.start)} – {formatDuration(activeClip.start + activeClip.duration)}</p>
                </div>
              </div>
            ) : (
              <p className="rounded-md bg-background px-3 py-2 text-xs text-muted">Select a program clip to inspect its properties.</p>
            )}
          </section>

          <section className="space-y-4 border-b border-border p-4">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-text">Transform <ChevronDown size={14} /></div>
            {activeClip && slider('Scale', activeClip.scale, 10, 300, 1, 'scale', '%')}
            <div className="space-y-3">
              {activeClip && slider('Position X', activeClip.positionX, -500, 500, 1, 'positionX')}
              {activeClip && slider('Position Y', activeClip.positionY, -500, 500, 1, 'positionY')}
              {activeClip && slider('Rotation', activeClip.rotation, -180, 180, 1, 'rotation', '°')}
              {activeClip && slider('Opacity', activeClip.opacity, 0, 100, 1, 'opacity', '%')}
            </div>
          </section>

          <section className="space-y-3 p-4">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-text">Audio <ChevronDown size={14} /></div>
            <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2.5 text-xs text-muted">
              <AudioLines size={14} className="text-accent" />
              {activeClip ? cameras[activeClip.sourceIndex ?? -1]?.state ?? 'Source audio' : 'No clip selected'}
            </div>
          </section>
          <section className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted">
            <span className="flex items-center gap-2"><Gauge size={14} /> Speed</span>
            <span className="rounded border border-border bg-background px-2 py-1 font-mono text-text">1.0×</span>
          </section>
        </div>
      ) : (
        <div className="space-y-4 p-4 text-xs">
          <p className="text-sm font-semibold text-text">Clip Metadata</p>
          {activeClip ? (
            <dl className="space-y-3">
              <MetadataRow label="Name" value={activeClip.name} />
              <MetadataRow label="Start" value={`${activeClip.start.toFixed(3)} s`} />
              <MetadataRow label="Duration" value={`${activeClip.duration.toFixed(3)} s`} />
              <MetadataRow label="Confidence" value={typeof activeClip.confidence === 'number' && activeClip.confidence > 0 ? `${(activeClip.confidence <= 1 ? activeClip.confidence * 100 : activeClip.confidence).toFixed(1)}%` : 'Not measured'} />
              <MetadataRow label="Track" value={activeClip.track === 0 ? 'V1 · Program' : `V${activeClip.track + 1}`} />
              <MetadataRow label="Sync state" value={cameras[activeClip.sourceIndex ?? -1]?.state ?? 'Not measured'} />
            </dl>
          ) : (
            <p className="rounded-md bg-background p-3 text-muted">Select a clip to view its metadata.</p>
          )}
        </div>
      )}
    </aside>
  );
}

function MetadataRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border pb-2">
      <dt className="text-muted">{label}</dt>
      <dd className="max-w-[65%] break-all text-right font-medium text-text">{value}</dd>
    </div>
  );
}

export default function Workspace() {
  const { projectId } = useParams<{ projectId: string }>();
  const { projects, updateProjectStatus } = useProjectStore();
  const currentProject = projects.find((project) => project.id === projectId) ?? { id: projectId ?? 'default-project', name: 'Wedding Ceremony', cameraCount: 0, status: 'Draft' };
  
  const sessionId = useStore((state) => state.sessionId);
  const jobId = useStore((state) => state.jobId);
  const files = useStore((state) => state.files);
  const allSources = useStore((state) => state.allSources);
  const segments = useStore((state) => state.segments);
  const pipeline = useStore((state) => state.pipeline);
  const cameras = useStore((state) => state.syncData);
  const setSessionId = useStore((state) => state.setSessionId);
  const setClips = useEditorStore((state) => state.setClips);
  const undo = useEditorStore((state) => state.undo);
  const redo = useEditorStore((state) => state.redo);
  const undoStack = useEditorStore((state) => state.undoStack);
  const redoStack = useEditorStore((state) => state.redoStack);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [tourRun, setTourRun] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [menu, setMenu] = useState<'File' | 'Edit' | 'View' | null>(null);
  const isReady = pipeline.stage === 'ready';
  const isWorking = !['idle', 'ready', 'failed'].includes(pipeline.stage);
  const cameraCount = Math.max(cameras.length, allSources.length, files.length);

  // Sync segments to editor clips
  const editorClips = useMemo(() => buildEditorClips(segments, cameras, allSources), [segments, cameras, allSources]);
  useEffect(() => { setClips(editorClips); }, [editorClips, setClips]);

  // Load project on mount
  useEffect(() => {
    if (!projectId) return;
    setSessionId(projectId);
    useEditorStore.getState().setPlayhead(0);
    useEditorStore.getState().setIsPlaying(false);
    let active = true;
    loadSessionProject(projectId)
      .then((project) => {
        if (!active) return;
        const state = useStore.getState();
        state.loadProjectFile(project);
        const sources = project.cameras.map((_, index) => getSessionMediaUrl(projectId, index));
        state.setAllSources(sources);
        state.setDuration(Math.max(0, ...project.cameras.map((camera) => camera.offset_s + (camera.duration_sec ?? 0))));
        
        // Immediately rehydrate the editor clips so the timeline populates instantly on load
        const restoredClips = buildEditorClips(project.program, project.cameras, sources);
        useEditorStore.getState().setClips(restoredClips);
      })
      .catch((error: any) => {
        if (error?.response?.status !== 404) {
          toast.error('Could not restore the saved timeline.', { description: error?.response?.data?.error ?? error?.message });
        }
      });
    return () => { active = false; };
  }, [projectId, setSessionId]);

  // Auto-save project
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = useStore.subscribe((state) => {
      if (state.pipeline.stage !== 'ready' || state.syncData.length === 0) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        saveSessionProject(state.sessionId, state.toProjectFile()).catch((error: any) => {
          toast.error('Could not save the project JSON.', { description: error?.response?.data?.error ?? error?.message });
        });
      }, 500);
    });
    return () => { unsubscribe(); if (timer) clearTimeout(timer); };
  }, []);

  const handleSaveProject = async () => {
    try {
      await saveSessionProject(sessionId, useStore.getState().toProjectFile());
      toast.success('Project saved.');
    } catch (error: any) {
      toast.error('Could not save this project.', { description: error?.response?.data?.error ?? error?.message });
    }
  };

  const commitEditorClips = useCallback((clips: EditorClip[]) => {
    const state = useStore.getState();
    state.editProgramSegments(clips.map((clip) => {
      const previous = state.segments.find((segment) => segment.id === clip.id);
      return {
        id: clip.id, camera: clip.name, start: clip.start, end: clip.start + clip.duration,
        confidence: clip.confidence, reason: clip.reason ?? previous?.reason, source: 'manual',
      };
    }));
  }, []);
  const handleEditorUndo = () => { undo(); commitEditorClips(useEditorStore.getState().clips); };
  const handleEditorRedo = () => { redo(); commitEditorClips(useEditorStore.getState().clips); };

  const handleImport = async (selected: File[]) => {
    if (!selected.length) return;
    if (selected.length < 2 || selected.length > 8) {
      toast.error('Select between 2 and 8 camera files to synchronize.');
      return;
    }
    const unsupported = selected.filter((file) => !file.type.startsWith('video/') && !file.type.startsWith('audio/') && !/\.(mp4|mov|m4v|mkv|avi|webm|mts|m2ts|ts|mpg|mpeg|3gp|wmv|mp3|wav|m4a|aac|flac|ogg)$/i.test(file.name));
    if (unsupported.length) {
      toast.error(`Unsupported media: ${unsupported.map((file) => file.name).join(', ')}`);
      return;
    }

    setIsUploading(true);
    const state = useStore.getState();
    state.setFiles(selected);
    state.setAllSources(selected.map((file) => URL.createObjectURL(file)));
    state.clearOverrides();
    state.setMasterAudioUrl(null);
    state.setSyncReport(null);
    state.setSyncData([]);
    state.setSegments([]);
    state.setDuration(0);
    state.setSyncStartedAt(Date.now());
    useEditorStore.getState().setClips([]);
    useEditorStore.getState().setPlayhead(0);
    useEditorStore.getState().setIsPlaying(false);
    state.setPipeline({ stage: 'uploading', percentage: null, message: 'Uploading camera media…', jobStatus: null });

    try {
      const id = await uploadFiles(state.sessionId, selected, (percentage) => {
        useStore.getState().setPipeline({ stage: 'uploading', percentage, message: 'Uploading camera media…' });
      });
      useStore.getState().setJobId(id);
      useStore.getState().setSyncStartedAt(Date.now());
      useStore.getState().setPipeline({ stage: 'syncing', percentage: null, message: 'Waiting for worker status', jobStatus: 'PENDING' });
    } catch (error: any) {
      const message = error?.response?.data?.error ?? (error?.response?.status === 413 ? 'The selected files exceed the server upload limit.' : error?.message) ?? 'Could not upload the selected camera files.';
      useStore.getState().setPipeline({ stage: 'failed', percentage: null, message, jobStatus: 'FAILURE' });
      useStore.getState().setJobId(null);
      toast.error('Camera upload failed.', { description: message });
    } finally {
      setIsUploading(false);
    }
  };

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let terminal = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const result = await getJobStatus(jobId);
        if (cancelled) return;
        const state = useStore.getState();
        const metadata = result.metadata ?? {};
        const statusText = String(metadata.status || '');
        const stage = (metadata.stage as PipelineStage) ?? (statusText.toLowerCase().includes('rough cut') || statusText.startsWith('Analyzing ') || statusText.startsWith('AI rough cut:') ? 'ai_cutting' : 'syncing');
        const percentage = typeof metadata.total === 'number' && metadata.total > 0 && typeof metadata.current === 'number' ? Math.min(100, Math.max(0, metadata.current / metadata.total * 100)) : null;

        if (result.status === 'SUCCESS') {
          terminal = true;
          const response = result.result;
          const syncData: CameraSync[] = Array.isArray(response?.sync_data) ? response.sync_data : [];
          const suggested: Segment[] = Array.isArray(response?.segments) ? response.segments : [];
          const program = buildProgramDraft(suggested, syncData);
          
          state.setSyncData(syncData);
          state.setSuggestedSegments(suggested);
          state.setSegments(program);
          state.setDuration(Math.max(0, ...syncData.map((camera) => Number(camera.offset_s ?? 0) + Number(camera.duration_sec ?? 0))));
          
          if (response?.master_audio_url) state.setMasterAudioUrl(response.master_audio_url);
          
          const elapsed = state.syncStartedAt ? Math.max(1, Math.round((Date.now() - state.syncStartedAt) / 1000)) : 0;
          state.setSyncReport({
            totalSyncSeconds: elapsed, cameraCount: syncData.length,
            lockedCount: syncData.filter((camera) => camera.state === 'LOCKED').length,
            loopErrorMs: Math.abs(Number(response?.loop_error_s ?? 0)) * 1000,
            driftMsPerHour: syncData.reduce((sum, camera) => sum + Math.abs(Number(camera.drift_ms_per_hour ?? 0)), 0),
            suggestedCuts: program.length,
          });
          state.setPipeline({
            stage: program.length ? 'ready' : 'failed', percentage: program.length ? 100 : null,
            message: program.length ? 'Synchronized. Program is ready to edit.' : 'Sync finished but no video program could be assembled.',
            jobStatus: program.length ? 'SUCCESS' : 'FAILURE',
          });
          if (program.length && projectId) updateProjectStatus(projectId, 'Ready for Export');
          state.setJobId(null);
          if (!program.length) toast.error('Sync completed, but no program timeline could be assembled.');
        } else if (['FAILURE', 'REVOKED'].includes(result.status)) {
          terminal = true;
          state.setPipeline({ stage: result.status === 'REVOKED' ? 'idle' : 'failed', percentage: null, message: result.metadata?.status || result.error || (result.status === 'REVOKED' ? 'Job cancelled.' : 'Background job failed.'), jobStatus: result.status });
          state.setJobId(null);
          if (result.status === 'FAILURE') toast.error('Background sync failed.', { description: result.error });
        } else if (result.status === 'STALLED') {
          state.setPipeline({ stage, percentage: null, message: 'No progress update for 90 seconds.', jobStatus: 'STALLED' });
        } else {
          state.setPipeline({ stage, percentage, message: result.status === 'UNKNOWN' ? 'Backend status unavailable; reconnecting…' : metadata.status || 'Waiting for worker status', jobStatus: result.status });
        }
      } catch {
        if (!cancelled) {
          const state = useStore.getState();
          state.setPipeline({ stage: state.pipeline.stage, percentage: null, message: 'Cannot reach the SyncCut backend; retrying…', jobStatus: 'UNKNOWN' });
        }
      }
      if (!cancelled && !terminal) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [jobId, projectId, updateProjectStatus]);

  const measuredConfidences = cameras.map((camera) => Number(camera.link_confidence ?? camera.confidence)).filter(Number.isFinite).map((value) => value <= 1 ? value * 100 : value);
  const confidence = measuredConfidences.length ? measuredConfidences.reduce((sum, value) => sum + value, 0) / measuredConfidences.length : null;

  return (
    <div className="grid h-screen w-screen grid-rows-[52px_minmax(0,1fr)_210px] overflow-hidden bg-background text-text">
      <header className="z-40 flex min-w-0 items-center gap-4 border-b border-border bg-panel px-4">
        <Link to="/dashboard" className="flex shrink-0 items-center gap-2 text-base font-bold text-text">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-accent/15 text-accent"><Clapperboard size={18} /></span>
          <span>SyncCut <span className="text-accent">Studio</span></span>
        </Link>
        <span className="h-6 w-px bg-border" />
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="max-w-48 truncate text-sm font-semibold text-text">{currentProject.name}</span>
        </div>
        <nav className="hidden items-center gap-1 border-l border-border pl-3 md:flex">
          {(['File', 'Edit', 'View'] as const).map((item) => (
            <div key={item} className="relative">
              <button type="button" onClick={() => setMenu(menu === item ? null : item)} className={`rounded px-2.5 py-1.5 text-xs font-medium ${menu === item ? 'bg-white/10 text-white' : 'text-muted hover:bg-white/5 hover:text-text'}`}>{item}</button>
              {menu === item && (
                <div className="absolute left-0 top-full z-50 mt-2 min-w-44 rounded-md border border-border bg-panel p-1 shadow-xl">
                  {item === 'File' && <button type="button" onClick={() => { setMenu(null); fileInputRef.current?.click(); }} className="w-full rounded px-2.5 py-2 text-left text-xs text-text hover:bg-white/10">Import Media</button>}
                  {item === 'Edit' && (<><button type="button" onClick={() => { setMenu(null); handleEditorUndo(); }} className="w-full rounded px-2.5 py-2 text-left text-xs text-text hover:bg-white/10">Undo</button><button type="button" onClick={() => { setMenu(null); handleEditorRedo(); }} className="w-full rounded px-2.5 py-2 text-left text-xs text-text hover:bg-white/10">Redo</button></>)}
                  {item === 'View' && <button type="button" onClick={() => { setMenu(null); setTourRun(true); }} className="w-full rounded px-2.5 py-2 text-left text-xs text-text hover:bg-white/10">Workspace tour</button>}
                </div>
              )}
            </div>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span data-tour="sync-status" className={`hidden items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] sm:inline-flex ${isReady ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-border text-muted'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${isReady ? 'bg-emerald-400' : isWorking ? 'animate-pulse bg-accent' : 'bg-gray-600'}`} />
            {isReady ? `${cameraCount} Cams Synced${confidence === null ? '' : ` · ${confidence.toFixed(1)}%`}` : `${pipeline.message}${pipeline.percentage === null ? '' : ` · ${Math.round(pipeline.percentage)}%`}`}
          </span>
          <button type="button" title="Undo" onClick={handleEditorUndo} disabled={!undoStack.length} className="hidden h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 disabled:opacity-30 sm:grid"><Undo2 size={16} /></button>
          <button type="button" title="Redo" onClick={handleEditorRedo} disabled={!redoStack.length} className="hidden h-8 w-8 place-items-center rounded text-muted hover:bg-white/5 disabled:opacity-30 sm:grid"><Redo2 size={16} /></button>
          <Button type="button" size="sm" onClick={handleSaveProject} disabled={!cameraCount} className="h-9 bg-accent px-3 text-xs font-bold text-[#0a0a0c] hover:brightness-110 disabled:bg-border disabled:text-muted"><Save size={14} className="mr-2" /> Save Project</Button>
          <Button type="button" size="sm" onClick={() => setExportOpen(true)} disabled={!isReady} data-tour="export-button" className="h-9 bg-accent px-4 text-xs font-bold text-[#0a0a0c] hover:brightness-110 disabled:bg-border disabled:text-muted"><Download size={14} className="mr-2" /> Export</Button>
          <button type="button" aria-label="Workspace tour" onClick={() => setTourRun(true)} className="grid h-8 w-8 place-items-center rounded-full bg-[#233451] text-xs font-bold text-text hover:bg-[#2e466b]">S</button>
        </div>
      </header>

      <main className="grid min-h-0 grid-cols-[280px_minmax(0,1fr)_320px] overflow-hidden">
        <MediaPool onImport={handleImport} importing={isUploading} fileInputRef={fileInputRef} />
        <ProgramMonitor />
        <Inspector />
      </main>

      <Timeline onCommitClips={commitEditorClips} />

      <OnboardingTour run={tourRun} onRunChange={setTourRun} />
      <button type="button" onClick={() => setTourRun(true)} aria-label="Start the SyncCut workspace tour" className="fixed bottom-[220px] right-4 z-[90] grid h-10 w-10 place-items-center rounded-full border border-accent/50 bg-panel text-accent shadow-lg transition hover:bg-accent hover:text-[#0a0a0c]"><CircleHelp size={18} /></button>
      <ExportModal open={exportOpen} onOpenChange={setExportOpen} />
    </div>
  );
}