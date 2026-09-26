import { describe, expect, it } from 'vitest';
import { isTranscribableMedia, TRANSCRIBE_ACCEPT } from './transcribable-media';

describe('isTranscribableMedia', () => {
  it('accepts audio and video by MIME type', () => {
    expect(isTranscribableMedia({ name: 'a', type: 'audio/mpeg' })).toBe(true);
    expect(isTranscribableMedia({ name: 'b', type: 'video/mp4' })).toBe(true);
  });

  it('falls back to the extension when the OS reports no MIME type', () => {
    expect(isTranscribableMedia({ name: 'Meeting.MP4', type: '' })).toBe(true);
    expect(isTranscribableMedia({ name: 'call.mkv', type: '' })).toBe(true);
  });

  it('rejects non-media drops', () => {
    expect(isTranscribableMedia({ name: 'notes.pdf', type: 'application/pdf' })).toBe(false);
    expect(isTranscribableMedia({ name: 'notes.txt', type: '' })).toBe(false);
  });

  it('lets the file picker offer video recordings', () => {
    expect(TRANSCRIBE_ACCEPT).toContain('video/*');
    expect(TRANSCRIBE_ACCEPT).toContain('.mp4');
  });
});
