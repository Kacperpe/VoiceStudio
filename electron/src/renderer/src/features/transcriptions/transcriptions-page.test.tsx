import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('@/lib/api/client', () => ({ apiJson: mock.api, describeError: String }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
vi.mock('@tanstack/react-router', () => ({
  Link: (props: { children?: unknown }) => <a>{props.children as never}</a>,
  useNavigate: () => vi.fn(),
}));
vi.mock('@/hooks/use-engines', () => ({ useEngines: () => ({ data: undefined }) }));
vi.mock('@/hooks/use-dictation-selection', () => ({
  useDictationSelection: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-native-dictation', () => ({ useNativeShortcut: () => ({ data: undefined }) }));
vi.mock('@/features/settings/model-catalogue-query', () => ({
  useModelCatalogue: () => ({ data: undefined }),
}));
vi.mock('@/hooks/use-recording', () => ({
  useRecording: () => ({
    isStarting: false,
    isRecording: false,
    isCleaning: false,
    seconds: 0,
    selectedInputId: '',
    start: vi.fn(),
    stop: vi.fn(),
  }),
}));
vi.mock('@/components/recording-inputs', () => ({ RecordingInputs: () => null }));
vi.mock('@/components/workspace-sidebar', () => ({
  SecondarySidebar: (props: { children?: unknown }) => <aside>{props.children as never}</aside>,
}));
vi.mock('@/components/app-shell/workspace-header', () => ({
  WorkspaceHeader: (props: { children?: unknown }) => <header>{props.children as never}</header>,
}));
vi.mock('@/components/waveform-player', () => ({ WaveformPlayer: () => null }));
import { TranscriptionsPage } from './transcriptions-page';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

it('shows transcription progress and cancels the running request on the server', async () => {
  mock.api.mockImplementation((path: string, init?: { signal?: AbortSignal }) => {
    if (path.startsWith('/dictation/readiness')) return Promise.resolve({ ready: true });
    if (path === '/api/settings/dictation-refinement') return Promise.resolve({ auto: false });
    if (path.startsWith('/transcribe/progress/'))
      return Promise.resolve({ active: true, progress: 0.42 });
    if (path.startsWith('/transcribe/cancel/')) return Promise.resolve({ cancelled: true });
    if (path === '/transcribe')
      return new Promise((_resolve, reject) =>
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted'))),
      );
    return Promise.resolve({});
  });
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <TranscriptionsPage />
    </QueryClientProvider>,
  );
  const upload = await screen.findByRole('button', { name: 'clone.upload_audio' });
  await waitFor(() => expect(upload).toBeEnabled());
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(['x'], 'meeting.mp4', { type: 'video/mp4' })] },
  });

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('42%'), {
    timeout: 3000,
  });
  expect(screen.getByRole('progressbar')).toBeInTheDocument();
  const transcribeCall = mock.api.mock.calls.find(([path]) => path === '/transcribe');
  const id = (transcribeCall?.[1] as { body: FormData }).body.get('request_id');
  expect(id).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }));
  expect(mock.api).toHaveBeenCalledWith(`/transcribe/cancel/${id}`, { method: 'POST' });
  await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument());
});
