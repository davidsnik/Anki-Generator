export interface DesktopDownload {
  id: string;
  filename: string;
}
export interface DesktopInfo {
  desktop: true;
  application_version: string;
  platform: string;
  data_directory: string;
  state_directory: string;
  backend_version: string | null;
  status: string;
  message: string;
  details?: string;
  notifications_supported: boolean;
  tray_available: boolean;
  last_download: DesktopDownload | null;
}
export interface DesktopBridge {
  info: () => Promise<DesktopInfo>;
  diagnostics: () => Promise<Record<string, unknown>>;
  exportDiagnostics: () => Promise<{ saved: boolean }>;
  restartBackend: () => Promise<{ restarted: boolean }>;
  openDirectory: (kind: 'data' | 'logs' | 'exports' | 'downloads') => Promise<{ opened: boolean }>;
  openDownload: (id: string, action: 'file' | 'folder') => Promise<{ opened: boolean }>;
  onState: (callback: (info: DesktopInfo) => void) => () => void;
  onNavigate: (callback: (route: string) => void) => () => void;
  onDownload: (callback: (file: DesktopDownload) => void) => () => void;
}
declare global {
  interface Window {
    ankiDesktop?: DesktopBridge;
  }
}
export const desktopBridge = () => window.ankiDesktop;
export function desktopRoute(route: string) {
  return (
    typeof route === 'string' &&
    !route.startsWith('//') &&
    /^\/(?:tasks|courses|settings|evaluation)?(?:[/?#]|$)/.test(route) &&
    !route.includes('\\') &&
    !/[\u0000-\u001f]/.test(route)
  );
}
