import { describe, expect, it } from 'vitest';
import { suggestDocumentRole } from './documentRoles';
describe('visible filename role suggestions', () => {
  it('distinguishes exercises, solutions, lectures, notes, and references', () => {
    expect(suggestDocumentRole('week_02-exercises.pdf')).toBe('exercises');
    expect(suggestDocumentRole('exam-worked-solutions.pdf')).toBe('solutions');
    expect(suggestDocumentRole('Lecture_notes.pdf')).toBe('lecture');
    expect(suggestDocumentRole('my_personal_notes.pdf')).toBe('personal_notes');
    expect(suggestDocumentRole('course_syllabus.docx')).toBe('reference');
  });
  it('does not invent a role from an unknown filename', () => {
    expect(suggestDocumentRole('document42.pdf')).toBeNull();
  });
  it('does not treat a substring as a category marker', () => {
    expect(suggestDocumentRole('resolutions.pdf')).toBeNull();
  });
});
