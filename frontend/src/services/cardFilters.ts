export interface CardFilters {
  search: string;
  status: string;
  verification: string;
  type: string;
  topic: string;
  sourceFilter: string;
  sort: string;
  view: string;
}
export const defaultCardFilters: CardFilters = {
  search: '',
  status: 'all',
  verification: 'all',
  type: 'all',
  topic: 'all',
  sourceFilter: 'all',
  sort: 'newest',
  view: 'grid',
};
const choices: Partial<Record<keyof CardFilters, string[]>> = {
  status: ['all', 'pending', 'approved', 'rejected'],
  verification: [
    'all',
    'needs_attention',
    'verified',
    'unverified',
    'needs_review',
    'failed',
    'rejected',
    'duplicate',
  ],
  type: ['all', 'basic', 'cloze'],
  sort: ['newest', 'question', 'status'],
  view: ['grid', 'list', 'study'],
};
export function readCardFilters(courseId: string): CardFilters {
  const result = { ...defaultCardFilters };
  try {
    const saved = JSON.parse(sessionStorage.getItem(`anki-card-filters:${courseId}`) || '{}');
    if (!saved || typeof saved !== 'object') return result;
    for (const key of Object.keys(result) as (keyof CardFilters)[]) {
      const value = saved[key];
      if (
        typeof value === 'string' &&
        value.length <= 1000 &&
        (!choices[key] || choices[key]?.includes(value))
      )
        result[key] = value;
    }
  } catch {
    /* Storage may be unavailable or contain an older value. */
  }
  return result;
}
export function rememberCardFilters(courseId: string, value: CardFilters) {
  try {
    sessionStorage.setItem(`anki-card-filters:${courseId}`, JSON.stringify(value));
  } catch {
    /* Browsing remains available when storage is disabled. */
  }
}
