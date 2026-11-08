export type DocumentRole = 'lecture' | 'personal_notes' | 'exercises' | 'solutions' | 'reference';
/** A visible, editable filename hint; authority and correctness are never inferred. */
export function suggestDocumentRole(filename: string): DocumentRole | null {
  const name = filename.toLowerCase().replace(/[_\-.]+/g, ' ');
  if (/\b(solution|solutions|worked|answers|answer key)\b/.test(name)) return 'solutions';
  if (
    /\b(exercise|exercises|assignment|assignments|homework|exam|exams|problem|problems|worksheet)\b/.test(
      name,
    )
  )
    return 'exercises';
  if (/\b(personal|remarkable|handwritten)\b/.test(name)) return 'personal_notes';
  if (/\b(syllabus|objectives|formula|reference|references)\b/.test(name)) return 'reference';
  if (/\b(lecture|lectures|slides|reader|textbook|chapter)\b/.test(name)) return 'lecture';
  if (/\b(notes|summary|summaries)\b/.test(name)) return 'personal_notes';
  return null;
}
