import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { DesktopEvents, DesktopPanel } from './Desktop';
import { desktopRoute } from '../services/desktop';
import type { DesktopBridge, DesktopInfo } from '../services/desktop';
import { ToastProvider } from '../components/UI';
const info: DesktopInfo = {
  desktop: true,
  application_version: '1.0',
  platform: 'linux',
  data_directory: '/home/fixture/.local/share/anki-generator',
  state_directory: '/home/fixture/.local/state/anki-generator',
  backend_version: '1.0',
  status: 'ready',
  message: 'Ready',
  notifications_supported: false,
  tray_available: false,
  last_download: { id: 'approved-download-id', filename: 'mathematics.apkg' },
};
function bridge() {
  const noop = () => () => {};
  const value: DesktopBridge = {
    info: vi.fn(async () => info),
    diagnostics: vi.fn(async () => ({ schema_version: '0006', runtime: { active_jobs: 2 } })),
    exportDiagnostics: vi.fn(async () => ({ saved: true })),
    restartBackend: vi.fn(async () => ({ restarted: true })),
    openDirectory: vi.fn(async () => ({ opened: true })),
    openDownload: vi.fn(async () => ({ opened: true })),
    onState: noop,
    onNavigate: noop,
    onDownload: noop,
  };
  window.ankiDesktop = value;
  return value;
}
function wrap(node: React.ReactNode) {
  return render(
    <MemoryRouter>
      <QueryClientProvider
        client={
          new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
          })
        }
      >
        <ToastProvider>{node}</ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
afterEach(() => {
  delete window.ankiDesktop;
  vi.restoreAllMocks();
});
it('keeps the standalone browser UI free of desktop-only actions', () => {
  wrap(<DesktopPanel />);
  expect(screen.queryByText('Desktop workspace')).toBeNull();
});
it('opens only a named application directory and an approved download capability', async () => {
  const native = bridge();
  wrap(<DesktopPanel />);
  await screen.findByText('/home/fixture/.local/share/anki-generator');
  fireEvent.click(screen.getByRole('button', { name: 'Open data folder' }));
  await waitFor(() => expect(native.openDirectory).toHaveBeenCalledWith('data'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Show in folder' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Show in folder' }));
  await waitFor(() =>
    expect(native.openDownload).toHaveBeenCalledWith('approved-download-id', 'folder'),
  );
  expect(screen.getByText(/never silently overwrites/)).toBeInTheDocument();
});
it('exports safe diagnostics through the native save action and displays actual runtime details', async () => {
  const native = bridge();
  wrap(<DesktopPanel />);
  fireEvent.click(screen.getByRole('button', { name: 'Export desktop diagnostics' }));
  await waitFor(() => expect(native.exportDiagnostics).toHaveBeenCalledOnce());
  await screen.findByText('Safe application diagnostics saved.');
  fireEvent.click(screen.getByRole('button', { name: 'View desktop runtime details' }));
  await screen.findByText(/"schema_version": "0006"/);
  expect(native.diagnostics).toHaveBeenCalledOnce();
});
it('accepts only local application navigation and unsubscribes all narrow bridge listeners', async () => {
  const native = bridge();
  let navigate: ((route: string) => void) | undefined;
  const unsubscribe = vi.fn();
  native.onNavigate = (callback) => {
    navigate = callback;
    return unsubscribe;
  };
  function Location() {
    return <output data-testid="route">{useLocation().pathname}</output>;
  }
  const view = wrap(
    <>
      <DesktopEvents />
      <Location />
    </>,
  );
  act(() => navigate?.('//attacker.example'));
  expect(screen.getByTestId('route')).toHaveTextContent('/');
  act(() => navigate?.('/tasks'));
  expect(screen.getByTestId('route')).toHaveTextContent('/tasks');
  view.unmount();
  expect(unsubscribe).toHaveBeenCalled();
  for (const route of [
    'https://evil.example',
    '//evil.example',
    '/settings\\evil',
    '/tasks\nmalicious',
  ])
    expect(desktopRoute(route)).toBe(false);
  expect(desktopRoute('/settings#desktop-diagnostics')).toBe(true);
});
