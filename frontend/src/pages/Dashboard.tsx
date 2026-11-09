import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CheckCheck,
  Clock3,
  FileText,
  Layers,
  Plus,
  ShieldCheck,
  Sparkles,
  Upload,
  Zap,
} from 'lucide-react';
import type { Bootstrap, Course } from '../services/types';
import { write } from '../services/api';
import {
  Badge,
  Empty,
  ErrorPanel,
  formatDate,
  human,
  Modal,
  PageTitle,
  SectionHead,
  statusTone,
  useToast,
} from '../components/UI';
import { KeySetup } from './Settings';
import { CourseTaskStatus } from '../features/tasks/CourseTaskStatus';
export function CreateCourseModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [language, setLanguage] = useState('English');
  const [deck, setDeck] = useState('');
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const mutation = useMutation({
    mutationFn: () =>
      write<Course>('/courses', { name, description, language, deck_name: deck || name }),
    onSuccess: (course) => {
      client.invalidateQueries();
      toast('Your course is ready. Add your first materials.');
      onClose();
      navigate(`/courses/${course.id}/documents`);
    },
  });
  return (
    <Modal title="Make room for a new course" onClose={onClose}>
      <p className="muted">A home for your material, ideas, and the things worth remembering.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          Course name
          <input
            autoFocus
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Linear Algebra"
          />
        </label>
        <label>
          Description <span className="optional">optional</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What are you learning this semester?"
            rows={3}
          />
        </label>
        <div className="form-grid">
          <label>
            Anki deck name
            <input
              value={deck}
              onChange={(e) => setDeck(e.target.value)}
              placeholder={name || 'Course deck'}
            />
          </label>
          <label>
            Preferred language
            <input value={language} onChange={(e) => setLanguage(e.target.value)} required />
          </label>
        </div>
        {mutation.isError && <ErrorPanel error={mutation.error} />}
        <div className="form-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" disabled={mutation.isPending || !name.trim()}>
            <Plus size={16} />
            {mutation.isPending ? 'Creating…' : 'Create course'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function Welcome({ data, onCreate }: { data: Bootstrap; onCreate: () => void }) {
  return (
    <div className="welcome">
      <div className="hero-pill">
        <Sparkles size={14} /> A LITTLE STRUCTURE. A LOT MORE UNDERSTANDING.
      </div>
      <h1>
        Meet your new
        <br />
        <span>learning companion.</span>
      </h1>
      <p>
        Bring your course materials together. Build thoughtful flashcards grounded in the sources
        you trust.
      </p>
      <div className="onboard-grid">
        <section className="panel">
          <div className="step-number">01</div>
          <h2>Connect your intelligence</h2>
          <p className="muted">
            OpenAI powers interpretation and independent review. Your key stays on the backend.
          </p>
          <KeySetup status={data.key_status} />
        </section>
        <section className="panel">
          <div className="step-number">02</div>
          <h2>Create your first course</h2>
          <p className="muted">
            Give your lectures, exercises, and notes a shared home. You’re in control of when
            processing starts.
          </p>
          <button className="button primary" onClick={onCreate}>
            <Plus size={17} /> Create a course
          </button>
        </section>
      </div>
      <div className="inline-note">
        <ShieldCheck size={19} /> Materials remain local until you explicitly approve a processing
        run.
      </div>
    </div>
  );
}
export function Dashboard({
  data,
  onCreate,
  coursesOnly = false,
}: {
  data: Bootstrap;
  onCreate: () => void;
  coursesOnly?: boolean;
}) {
  const [showArchived, setShowArchived] = useState(false);
  const courses = data.courses.filter((c) => showArchived || !c.archived);
  const totals = data.courses.reduce(
    (acc, c) => ({
      documents: acc.documents + (c.stats?.documents ?? c.document_count ?? 0),
      cards: acc.cards + (c.stats?.cards ?? c.card_count ?? 0),
      pending: acc.pending + (c.stats?.pending_review ?? c.pending_count ?? 0),
    }),
    { documents: 0, cards: 0, pending: 0 },
  );
  return (
    <>
      <PageTitle
        eyebrow="YOUR LEARNING WORKSPACE"
        title={coursesOnly ? 'Every course, one clear view.' : 'Good things take understanding.'}
        description={
          coursesOnly
            ? 'Bring your materials together and turn a semester of ideas into lasting knowledge.'
            : 'A little more connected. A little better remembered. Pick up where you left off.'
        }
        actions={
          <button className="button primary" onClick={onCreate}>
            <Plus size={17} /> Create course
          </button>
        }
      />
      {!coursesOnly && (
        <>
          <div className="overview-hero">
            <div className="hero-copy">
              <div className="hero-pill">
                <span /> THOUGHTFUL FLASHCARDS. LASTING KNOWLEDGE.
              </div>
              <h2>
                From a semester of material
                <br />
                to a mind full of <em>possibilities.</em>
              </h2>
              <p>
                Your lectures, notes, and exercises. Connected into a clearer picture, one
                well-crafted card at a time.
              </p>
              <Link
                className="button hero-button"
                to={data.courses.length ? `/courses/${data.courses[0].id}/documents` : '/welcome'}
              >
                {data.courses.length ? 'Continue learning' : 'Set up your workspace'}
                <ArrowUpRight size={17} />
              </Link>
            </div>
            <div className="hero-art" aria-hidden="true">
              <div className="orbit orbit-one" />
              <div className="orbit orbit-two" />
              <div className="floating-card back">
                <span className="art-lines" />
                <span className="art-lines short" />
                <span className="art-equation">∑ knowledge</span>
              </div>
              <div className="floating-card front">
                <div className="mini-label">
                  <Sparkles size={13} /> THE BIGGER PICTURE
                </div>
                <span className="art-symbol">a² + b²</span>
                <span className="art-lines" />
                <span className="art-lines short" />
                <div className="art-bottom">
                  <span className="art-tag">Connected ideas</span>
                  <CheckCheck size={18} />
                </div>
              </div>
              <div className="art-spark one">✦</div>
              <div className="art-spark two">✧</div>
              <div className="art-circle">
                <BookOpen size={23} />
              </div>
            </div>
          </div>
          <div className="stats-grid">
            {[
              {
                label: 'Active courses',
                value: data.courses.filter((c) => !c.archived).length,
                icon: BookOpen,
                color: 'violet',
                note: 'Spaces for your ideas',
              },
              {
                label: 'Source documents',
                value: totals.documents,
                icon: FileText,
                color: 'blue',
                note: 'The foundation of your deck',
              },
              {
                label: 'Flashcards created',
                value: totals.cards,
                icon: Layers,
                color: 'green',
                note: 'Built for understanding',
              },
              {
                label: 'Awaiting your review',
                value: totals.pending,
                icon: CheckCheck,
                color: 'amber',
                note: 'Your judgment matters',
              },
            ].map((item) => (
              <div className="stat-card" key={item.label}>
                <div>
                  <span>{item.label}</span>
                  <strong>{item.value.toLocaleString()}</strong>
                  <small>{item.note}</small>
                </div>
                <div className={`stat-icon ${item.color}`}>
                  <item.icon size={21} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      <SectionHead
        title="Your courses"
        action={
          <div className="inline-actions">
            <label className="check-label">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
              />{' '}
              Include archived
            </label>
            {!coursesOnly && (
              <Link className="text-link" to="/courses">
                View all courses <ArrowRight size={15} />
              </Link>
            )}
          </div>
        }
      >
        A place for every subject, and every connection.
      </SectionHead>
      <div className="courses-grid">
        {courses.map((course, i) => (
          <article className="course-card" key={course.id}>
            <Link className="course-card-link" to={`/courses/${course.id}`}>
              <div className="course-card-top">
                <div className={`course-icon color-${i % 4}`}>
                  <BookOpen size={23} />
                </div>
                <Badge tone={statusTone(course.last_run_status || course.stats?.last_status)}>
                  {course.archived
                    ? 'Archived'
                    : (course.last_run_status || course.stats?.last_status) !== 'not_started' &&
                        (course.last_run_status || course.stats?.last_status)
                      ? human(course.last_run_status || course.stats?.last_status)
                      : 'Ready to explore'}
                </Badge>
              </div>
              <h3>{course.name}</h3>
              <p>
                {course.description || 'A fresh perspective starts with your course materials.'}
              </p>
              <div className="course-stats">
                <span>
                  <FileText size={14} />
                  {course.stats?.documents ?? course.document_count ?? 0} documents
                </span>
                <span>
                  <Layers size={14} />
                  {course.stats?.cards ?? course.card_count ?? 0} cards
                </span>
              </div>
            </Link>
            <CourseTaskStatus
              courseId={course.id}
              courseName={course.name}
              compact
              fallback={course.active_task}
            />
            <Link to={`/courses/${course.id}`} className="course-card-footer">
              <span>
                {course.language || 'English'} · {course.deck_name || course.name}
              </span>
              <ArrowUpRight size={18} />
            </Link>
          </article>
        ))}
        <button className="new-course-card" onClick={onCreate}>
          <span>
            <Plus size={24} />
          </span>
          <strong>Create a new course</strong>
          <small>What will you understand next?</small>
        </button>
      </div>
      {!coursesOnly && (
        <div className="dashboard-bottom">
          <section className="panel">
            <SectionHead title="Recent activity" action={<Clock3 size={19} />}>
              The latest from your workspace.
            </SectionHead>
            {!data.recent_runs?.length ? (
              <Empty icon={Zap} title="Your next breakthrough awaits">
                Processing runs will appear here as you turn materials into a connected deck.
              </Empty>
            ) : (
              <div className="activity-list">
                {data.recent_runs.slice(0, 5).map((run) => (
                  <Link key={run.id} to={`/tasks/${run.id}`}>
                    <div className={`activity-icon ${statusTone(run.status)}`}>
                      <Zap size={17} />
                    </div>
                    <div>
                      <strong>
                        {data.courses.find((c) => c.id === run.course_id)?.name ||
                          'Course processing'}
                      </strong>
                      <span>
                        {human(run.current_stage || run.stage || run.status)} ·{' '}
                        {formatDate(run.created_at)}
                      </span>
                    </div>
                    <Badge tone={statusTone(run.status)}>{human(run.status)}</Badge>
                  </Link>
                ))}
              </div>
            )}
          </section>
          <section className="tip-card">
            <div className="tip-icon">
              <Sparkles size={23} />
            </div>
            <div className="eyebrow">BETTER TOGETHER</div>
            <h3>More than lecture notes.</h3>
            <p>
              Exercises reveal what you need to <em>do</em> with your knowledge. Import them
              alongside lectures for a richer, more useful deck.
            </p>
            <Link
              className="text-link"
              to={data.courses.length ? `/courses/${data.courses[0].id}/documents` : '/welcome'}
            >
              Bring your materials together <Upload size={15} />
            </Link>
          </section>
        </div>
      )}
    </>
  );
}
