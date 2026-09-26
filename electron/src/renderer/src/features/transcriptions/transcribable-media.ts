// The backend decodes anything ffmpeg reads, so meeting recordings (MP4/MKV/MOV)
// transcribe as well as plain audio.
const TRANSCRIBE_EXTENSIONS = [
  '.wav',
  '.mp3',
  '.m4a',
  '.flac',
  '.ogg',
  '.opus',
  '.aac',
  '.webm',
  '.mp4',
  '.mkv',
  '.mov',
  '.avi',
];

export const TRANSCRIBE_ACCEPT = ['audio/*', 'video/*', ...TRANSCRIBE_EXTENSIONS].join(',');

export function isTranscribableMedia(file: Pick<File, 'name' | 'type'>): boolean {
  if (file.type.startsWith('audio/') || file.type.startsWith('video/')) return true;
  const name = file.name.toLowerCase();
  return TRANSCRIBE_EXTENSIONS.some((extension) => name.endsWith(extension));
}
