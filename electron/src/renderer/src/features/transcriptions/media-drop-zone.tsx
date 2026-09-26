import { useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { UploadCloudIcon } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { isTranscribableMedia } from './transcribable-media';

/** Dashed drop target that feeds a dropped audio/video file into the same
 * transcription path as the upload button; clicking it opens the picker. */
export function MediaDropZone({
  disabled,
  onBrowse,
  onFile,
}: {
  disabled: boolean;
  onBrowse: () => void;
  onFile: (file: File) => void;
}) {
  const { t } = useTranslation();
  const [dragging, setDragging] = useState(false);
  // A <div>, not a disabled <button>: Chromium drops drag events on disabled
  // controls, and an unhandled drop makes Electron navigate to the file.
  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label={t('dub.drop_here')}
      className={cn(
        'flex w-full cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-border/60 bg-muted/10 px-4 py-6 text-sm text-muted-foreground transition-colors hover:border-primary/60 hover:bg-muted/30 focus-visible:outline-ring',
        disabled && 'cursor-not-allowed opacity-50 hover:border-border/60 hover:bg-muted/10',
        dragging && 'border-primary bg-primary/10 text-foreground',
      )}
      onClick={() => {
        if (!disabled) onBrowse();
      }}
      onKeyDown={(event) => {
        if (disabled || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        onBrowse();
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files[0];
        if (disabled || !file) return;
        if (!isTranscribableMedia(file)) {
          toast.error(t('clone.unsupported_audio'));
          return;
        }
        onFile(file);
      }}
    >
      <UploadCloudIcon className="size-5 shrink-0" aria-hidden="true" />
      {t('dub.drop_here')}
    </div>
  );
}
