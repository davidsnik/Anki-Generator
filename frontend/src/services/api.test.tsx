import { afterEach, expect, it, vi } from 'vitest';
import { api } from './api';
afterEach(() => vi.unstubAllGlobals());
it('explains invalid fields without exposing raw validation payloads or input secrets', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            loc: ['body', 'models', 'generation'],
            msg: 'Choose an available model',
            input: 'private-input',
          },
        ],
      }),
    }),
  );
  await expect(api('/settings')).rejects.toThrow('models → generation: Choose an available model');
  await expect(api('/settings')).rejects.not.toThrow('private-input');
});
it('gives an actionable connection error when the workspace is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
  await expect(api('/courses')).rejects.toThrow('The workspace could not be reached');
});
