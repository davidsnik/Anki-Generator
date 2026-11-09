import { useState } from 'react';
import { Link, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Archive,
  ArrowLeft,
  BookOpen,
  CheckCheck,
  Download,
  FileText,
  Layers,
  Network,
  Play,
  Save,
  Settings2,
  Trash2,
  Workflow,
} from 'lucide-react';
import { api, write } from '../services/api';
import type { Course, Json } from '../services/types';
import {
  Badge,
  Confirm,
  ErrorPanel,
  Loading,
  PageTitle,
  SectionHead,
  useToast,
} from '../components/UI';
import { DocumentsPage } from './Documents';
import { ProcessingPage, RunDialog } from './Processing';
import { KnowledgePage } from './Knowledge';
import { CardsPage } from './Cards';
import { ExportsPage } from './Exports';
import { useTasks } from '../features/tasks/live';
import { CourseTaskStatus } from '../features/tasks/CourseTaskStatus';
import { CriteriaForm } from './Settings';
export function CoursePage() {
  const { courseId } = useParams();
  const taskState = useTasks();
  const [generate, setGenerate] = useState(false);
  const course = useQuery({
    queryKey: ['course', courseId],
    queryFn: () => api<Course>(`/courses/${courseId}`),
    refetchInterval: 5000,
  });
  if (course.isPending) return <Loading />;
  if (course.isError) return <ErrorPanel error={course.error} retry={() => course.refetch()} />;
  const c = course.data;
  const active =
    taskState.data?.active_runs.find((task) => task.course_id === c.id) || c.active_task;
  return (
    <>
      <Link className="back-link" to="/courses">
        <ArrowLeft size={15} /> All courses
      </Link>
      <PageTitle
        eyebrow="COURSE WORKSPACE"
        title={c.name}
        description={c.description || 'Bring your sources together. Build your understanding.'}
        actions={
          <>
            <Badge tone={c.archived ? 'neutral' : 'green'}>
              {c.archived ? 'Archived' : 'Active course'}
            </Badge>
            <button
              className="button primary"
              disabled={!!active}
              title={
                active
                  ? 'This course already has an active task. Open its task details to manage it.'
                  : undefined
              }
              onClick={() => setGenerate(true)}
            >
              <Play size={16} /> Generate cards
            </button>
          </>
        }
      />
      <div className="course-meta">
        <span>
          <BookOpen size={14} />
          {c.deck_name || c.name}
        </span>
        <span>{c.language || 'English'}</span>
        <span>
          <CheckCheck size={14} /> Source-supported learning
        </span>
      </div>
      <CourseTaskStatus courseId={c.id} courseName={c.name} latest fallback={c.active_task} />
      <nav className="tabs" aria-label="Course sections">
        {[
          { path: 'documents', label: 'Documents', icon: FileText },
          { path: 'knowledge', label: 'Knowledge map', icon: Network },
          { path: 'cards', label: 'Flashcards', icon: Layers },
          { path: 'processing', label: 'Processing', icon: Workflow },
          { path: 'exports', label: 'Exports', icon: Download },
          { path: 'preferences', label: 'Preferences', icon: Settings2 },
        ].map((item) => (
          <NavLink key={item.path} to={`/courses/${c.id}/${item.path}`}>
            <item.icon size={17} />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<DocumentsPage course={c} />} />
        <Route path="documents" element={<DocumentsPage course={c} />} />
        <Route path="knowledge" element={<KnowledgePage course={c} />} />
        <Route path="cards" element={<CardsPage course={c} />} />
        <Route path="processing" element={<ProcessingPage course={c} />} />
        <Route path="exports" element={<ExportsPage course={c} />} />
        <Route path="preferences" element={<Preferences course={c} />} />
      </Routes>
      {generate && <RunDialog course={c} onClose={() => setGenerate(false)} />}
    </>
  );
}
function Preferences({ course }: { course: Course }) {
  const [data, setData] = useState(course);
  const [criteria, setCriteria] = useState<Json>(course.criteria || {});
  const [remove, setRemove] = useState(false);
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const save = useMutation({
    mutationFn: () =>
      write(
        `/courses/${course.id}`,
        {
          name: data.name,
          description: data.description,
          deck_name: data.deck_name,
          language: data.language,
          criteria,
        },
        'PATCH',
      ),
    onSuccess: () => {
      client.invalidateQueries();
      toast('Course preferences saved. Existing cards are preserved.');
    },
  });
  const archive = useMutation({
    mutationFn: () => write(`/courses/${course.id}`, { archived: !course.archived }, 'PATCH'),
    onSuccess: () => {
      client.invalidateQueries();
      toast(course.archived ? 'Course restored.' : 'Course archived.');
    },
  });
  const del = useMutation({
    mutationFn: () => api(`/courses/${course.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries();
      navigate('/courses');
      toast('Course deleted.');
    },
  });
  return (
    <div className="settings-layout">
      <div className="settings-main">
        <section className="panel">
          <SectionHead title="Course details" />
          <label>
            Course name
            <input value={data.name} onChange={(e) => setData({ ...data, name: e.target.value })} />
          </label>
          <label>
            Description
            <textarea
              rows={3}
              value={data.description || ''}
              onChange={(e) => setData({ ...data, description: e.target.value })}
            />
          </label>
          <div className="form-grid">
            <label>
              Anki deck name
              <input
                value={data.deck_name || ''}
                onChange={(e) => setData({ ...data, deck_name: e.target.value })}
              />
            </label>
            <label>
              Preferred language
              <input
                value={data.language || 'English'}
                onChange={(e) => setData({ ...data, language: e.target.value })}
              />
            </label>
          </div>
        </section>
        <section className="panel">
          <SectionHead title="Generation criteria">
            These preferences apply to this course. A new run reuses unchanged source extraction.
          </SectionHead>
          <CriteriaForm value={criteria} onChange={setCriteria} />
        </section>
        <button
          className="button primary"
          disabled={save.isPending || !data.name.trim()}
          onClick={() => save.mutate()}
        >
          <Save size={16} />
          {save.isPending ? 'Saving…' : 'Save course preferences'}
        </button>
        {save.error && <ErrorPanel error={save.error} />}
      </div>
      <aside>
        <section className="panel">
          <h3>Course lifecycle</h3>
          <p className="muted">
            Archive a completed course to keep your workspace focused. Its sources and cards stay
            available.
          </p>
          <button className="button" onClick={() => archive.mutate()}>
            <Archive size={16} />
            {course.archived ? 'Restore course' : 'Archive course'}
          </button>
          <hr />
          <p className="muted">
            Deleting removes this course and its local records. Export or back up anything you want
            to keep first.
          </p>
          <button className="button text-danger" onClick={() => setRemove(true)}>
            <Trash2 size={16} />
            Delete course
          </button>
          {(del.error || archive.error) && <ErrorPanel error={del.error || archive.error} />}
        </section>
      </aside>
      {remove && (
        <Confirm
          title={`Delete ${course.name}?`}
          onClose={() => setRemove(false)}
          onConfirm={() => del.mutate()}
        >
          This removes its documents, processing history, concepts, cards, and export records from
          this workspace. This cannot be undone.
        </Confirm>
      )}
    </div>
  );
}
