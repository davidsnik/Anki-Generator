import type { Bootstrap } from './types';
let csrfToken = '';
export function setCsrfToken(token: string) {
  csrfToken = token;
}
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  if (options.method && !['GET', 'HEAD'].includes(options.method))
    headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const data = await response.json();
      const detail = data.detail ?? data.error ?? data.message;
      message = typeof detail === 'string' ? detail : JSON.stringify(detail);
    } catch {
      /* HTTP fallback */
    }
    throw new ApiError(message, response.status);
  }
  if (
    options.method &&
    !['GET', 'HEAD'].includes(options.method) &&
    (path.startsWith('/runs/') ||
      path.startsWith('/tasks/') ||
      /\/courses\/[^/]+\/runs/.test(path) ||
      path === '/settings')
  )
    window.dispatchEvent(new Event('anki-task-change'));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function bootstrap() {
  const data = await api<Bootstrap>('/bootstrap');
  setCsrfToken(data.csrf_token);
  return data;
}
export const write = <T>(path: string, body: unknown = {}, method = 'POST') =>
  api<T>(path, { method, body: JSON.stringify(body) });
export function upload(
  courseId: string,
  files: File[],
  category: string,
  authority: string,
  onProgress: (n: number) => void,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('paths', JSON.stringify(files.map((f) => f.webkitRelativePath || f.name)));
    form.append('category', category);
    form.append('authority', authority);
    const request = new XMLHttpRequest();
    request.open('POST', `/api/courses/${courseId}/documents`);
    request.setRequestHeader('X-CSRF-Token', csrfToken);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () =>
      reject(
        new Error('The upload connection was interrupted. Check that the local server is running.'),
      );
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.responseText ? JSON.parse(request.responseText) : {});
      } else {
        try {
          reject(new Error(JSON.parse(request.responseText).detail ?? 'Upload rejected.'));
        } catch {
          reject(new Error(`Upload failed (${request.status}).`));
        }
      }
    };
    request.send(form);
  });
}
export function list<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === 'object') {
    for (const key of [
      'items',
      'datasets',
      'experiments',
      'cases',
      'documents',
      'cards',
      'concepts',
      'runs',
      'exports',
      'pages',
      'revisions',
      'models',
    ]) {
      const v = (value as Record<string, unknown>)[key];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}
export async function downloadBackup() {
  const response = await fetch('/api/backup', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
    credentials: 'same-origin',
  });
  if (!response.ok)
    throw new Error('Backup could not be created. Check local storage space and try again.');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'anki-generator-backup.zip';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
