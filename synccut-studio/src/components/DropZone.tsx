import { ChangeEvent, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

interface Props {
  onFiles: (files: File[]) => void;
  fileNames: string[];
  disabled?: boolean;
}

const MEDIA_EXTENSIONS = /\.(mp4|mov|m4v|mkv|avi|webm|mts|m2ts|ts|mpg|mpeg|3gp|wmv|mp3|wav|m4a|aac|flac|ogg)$/i;
const ACCEPTED_MEDIA = 'video/*,audio/*,.mp4,.mov,.m4v,.mkv,.avi,.webm,.mts,.m2ts,.ts,.mpg,.mpeg,.3gp,.wmv,.mp3,.wav,.m4a,.aac,.flac,.ogg';

const isMedia = (file: File) =>
  file.type.startsWith('video/') ||
  file.type.startsWith('audio/') ||
  MEDIA_EXTENSIONS.test(file.name);

export default function DropZone({ onFiles, fileNames, disabled }: Props) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handle = (files: File[]) => {
    if (disabled) return;
    const media = files.filter(isMedia);
    if (media.length !== files.length) {
      toast.error('Some files are not supported video or audio formats.');
    }
    if (media.length < 2) {
      toast.error('Select at least 2 video or audio files to sync.');
      return;
    }
    if (media.length > 8) {
      toast.error('Select no more than 8 camera files at a time.');
      return;
    }
    onFiles(media);
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    handle(Array.from(event.currentTarget.files ?? []));
    event.currentTarget.value = '';
  };

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label="Add camera clips"
      aria-disabled={disabled}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(event) => {
        if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => { event.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        handle(Array.from(event.dataTransfer.files));
      }}
      className={cn(
        'flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed px-4 py-5 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00E5FF]',
        over ? 'border-[#00E5FF] bg-[#00E5FF]/10' : 'border-[#2a2a32] bg-[#0a0a0c] hover:border-[#00E5FF]/60',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_MEDIA}
        className="hidden"
        disabled={disabled}
        onClick={(event) => event.stopPropagation()}
        onChange={handleInputChange}
      />
      <UploadCloud className={cn('h-6 w-6', over ? 'text-[#00E5FF]' : 'text-[#a1a1aa]')} />
      <p className="text-sm text-[#ededed]">Drop camera clips here or click to browse</p>
      <p className="text-xs text-[#a1a1aa]">Select 2–8 video/audio files. SyncCut detects every camera and measures the master clock.</p>
      {fileNames.length > 0 && (
        <ul className="mt-1 w-full space-y-0.5 text-left font-mono text-xs text-[#a1a1aa]">
          {fileNames.map((name, index) => (
            <li key={`${name}-${index}`} className="truncate">
              <span className="text-[#00E5FF]">{`Camera ${index + 1}`}</span> {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
