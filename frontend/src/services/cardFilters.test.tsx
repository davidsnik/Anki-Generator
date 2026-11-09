import { beforeEach, describe, expect, it } from 'vitest';
import { defaultCardFilters, readCardFilters, rememberCardFilters } from './cardFilters';
beforeEach(() => sessionStorage.clear());
describe('course-specific review preferences', () => {
  it('restores useful review choices without sharing them with another course', () => {
    rememberCardFilters('analysis', {
      ...defaultCardFilters,
      status: 'pending',
      search: 'compact',
      view: 'list',
    });
    expect(readCardFilters('analysis')).toMatchObject({
      status: 'pending',
      search: 'compact',
      view: 'list',
    });
    expect(readCardFilters('circuits')).toEqual(defaultCardFilters);
  });
  it('recovers from damaged and obsolete storage values', () => {
    sessionStorage.setItem('anki-card-filters:a', '{broken');
    expect(readCardFilters('a')).toEqual(defaultCardFilters);
    sessionStorage.setItem(
      'anki-card-filters:a',
      JSON.stringify({ status: 'deleted', view: 'terminal', search: 'theorem' }),
    );
    expect(readCardFilters('a')).toMatchObject({ status: 'all', view: 'grid', search: 'theorem' });
  });
});
