import { useEffect, useRef, useState } from 'react';
import { NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  CircleHelp,
  GraduationCap,
  LayoutDashboard,
  ListTodo,
  Menu,
  Moon,
  Plus,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from 'lucide-react';
import { bootstrap } from './services/api';
import type { Bootstrap } from './services/types';
import { ErrorPanel, Loading, ToastProvider } from './components/UI';
import { Dashboard, CreateCourseModal, Welcome } from './pages/Dashboard';
import { CoursePage } from './pages/Course';
import { TaskLiveProvider, GlobalTaskIndicator, useTasks } from './features/tasks/live';
import { TasksPage, TaskDetailPage } from './features/tasks/TasksPage';
import { SettingsPage } from './pages/Settings';
import { DesktopEvents } from './features/Desktop';
import { desktopBridge } from './services/desktop';
export default function App() {
  return (
    <ToastProvider>
      <DesktopEvents />
      <TaskLiveProvider>
        <Workspace />
      </TaskLiveProvider>
    </ToastProvider>
  );
}
function Workspace() {
  const query = useQuery({ queryKey: ['bootstrap'], queryFn: bootstrap, refetchInterval: 10000 });
  const tasks = useTasks();
  const [create, setCreate] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem('anki-theme') ?? 'light');
  const desktopThemeLoaded = useRef(false);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('anki-theme', theme);
  }, [theme]);
  useEffect(() => setMobile(false), [location.pathname]);
  useEffect(() => {
    const listener = (event: Event) => setTheme((event as CustomEvent<string>).detail);
    window.addEventListener('anki-theme-change', listener);
    return () => window.removeEventListener('anki-theme-change', listener);
  }, []);
  useEffect(() => {
    if (!desktopBridge() || !query.data || desktopThemeLoaded.current) return;
    desktopThemeLoaded.current = true;
    const preference = String(query.data.settings.theme || 'system');
    setTheme(
      preference === 'system'
        ? window.matchMedia?.('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : preference,
    );
  }, [query.data]);
  if (query.isPending)
    return (
      <div className="startup">
        <div className="brand-mark">
          <GraduationCap />
        </div>
        <Loading />
      </div>
    );
  if (query.isError && !query.data)
    return (
      <main className="startup">
        <ErrorPanel error={query.error} retry={() => query.refetch()} />
      </main>
    );
  const data = query.data!;
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobile ? 'open' : ''}`}>
        <NavLink className="brand" to="/">
          <span className="brand-mark">
            <GraduationCap size={24} />
          </span>
          <span>
            Anki<span className="brand-light">Generator</span>
            <small>YOUR KNOWLEDGE, CONNECTED</small>
          </span>
        </NavLink>
        <button className="workspace-select" onClick={() => navigate('/')}>
          <span className="workspace-avatar">P</span>
          <span>
            Personal workspace<small>Local · Private by design</small>
          </span>
          <ChevronDown size={15} />
        </button>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          <NavLink to="/" end>
            <LayoutDashboard size={19} /> Overview
          </NavLink>
          <NavLink to="/courses">
            <BookOpen size={19} /> My courses
            <span className="nav-count">{data.courses.length}</span>
          </NavLink>
          <NavLink to="/tasks" aria-label="Tasks">
            <ListTodo size={19} />
            Tasks
            {tasks.data && tasks.data.counts.active + tasks.data.counts.queued > 0 && (
              <span className="nav-count" aria-hidden="true">
                {tasks.data.counts.active + tasks.data.counts.queued}
              </span>
            )}
          </NavLink>
        </nav>
        <div className="nav-label courses-label">
          <span>YOUR COURSES</span>
          <button aria-label="Create course" onClick={() => setCreate(true)}>
            <Plus size={15} />
          </button>
        </div>
        <nav className="course-nav">
          {data.courses
            .filter((c) => !c.archived)
            .slice(0, 8)
            .map((course, i) => (
              <NavLink to={`/courses/${course.id}`} key={course.id}>
                <span className={`course-dot color-${i % 4}`} />
                <span>{course.name}</span>
              </NavLink>
            ))}
          {!data.courses.length && <p className="nav-empty">Your next semester starts here.</p>}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <ShieldCheck size={20} />
            <strong>Local first. Always yours.</strong>
            <p>Your materials stay on this device until you choose to process them.</p>
            <NavLink to="/settings">
              Privacy & settings <ArrowUpRight size={14} />
            </NavLink>
          </div>
          <nav>
            <NavLink to="/settings">
              <Settings size={19} /> Settings
              <span className={`connection-dot ${data.key_status.configured ? 'connected' : ''}`} />
            </NavLink>
            <a
              href="https://docs.ankiweb.net/importing/packaged-decks.html"
              target="_blank"
              rel="noreferrer"
            >
              <CircleHelp size={19} /> Anki import guide
              <ArrowUpRight size={14} />
            </a>
          </nav>
          <div className="profile">
            <span className="profile-avatar">You</span>
            <div>
              <strong>Your learning space</strong>
              <small>Made for deeper understanding</small>
            </div>
            <button
              className="icon-button"
              aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
              onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
            >
              {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
            </button>
          </div>
        </div>
      </aside>
      {mobile && <div className="sidebar-backdrop" onClick={() => setMobile(false)} />}
      <div className="main-shell">
        <div className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Toggle navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X /> : <Menu />}
            </button>
            <span>Workspace</span>
            <span>/</span>
            <strong>
              {location.pathname === '/settings'
                ? 'Settings'
                : location.pathname.startsWith('/tasks')
                  ? 'Tasks'
                  : location.pathname.startsWith('/courses/')
                    ? 'Course workspace'
                    : location.pathname === '/courses'
                      ? 'My courses'
                      : 'Overview'}
            </strong>
          </div>
          <div className="topbar-right">
            <GlobalTaskIndicator />
            <span className="local-indicator">
              <span /> Running locally
            </span>
            <button className="button small" onClick={() => setCreate(true)}>
              <Plus size={15} /> New course
            </button>
          </div>
        </div>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard data={data} onCreate={() => setCreate(true)} />} />
            <Route
              path="/welcome"
              element={<Welcome data={data} onCreate={() => setCreate(true)} />}
            />
            <Route
              path="/courses"
              element={<Dashboard data={data} onCreate={() => setCreate(true)} coursesOnly />}
            />
            <Route path="/courses/:courseId/*" element={<CoursePage />} />
            <Route path="/settings" element={<SettingsPage bootstrap={data} />} />
            <Route path="/tasks" element={<TasksPage courses={data.courses} />} />
            <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
            <Route
              path="*"
              element={
                <div className="empty">
                  <Sparkles />
                  <h1>A fresh start</h1>
                  <p>This page doesn’t exist.</p>
                  <NavLink className="button primary" to="/">
                    Back to overview
                  </NavLink>
                </div>
              }
            />
          </Routes>
        </main>
        <footer className="app-footer">
          <span>
            <ShieldCheck size={13} /> Your learning. Your data. Your pace.
          </span>
          <span>Anki Generator · Local workspace</span>
        </footer>
      </div>
      {create && <CreateCourseModal onClose={() => setCreate(false)} />}
    </div>
  );
}
export type { Bootstrap };
