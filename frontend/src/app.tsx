import { NavLink, Outlet, Route, Routes } from "react-router-dom";
import {
  BookOpen,
  LayoutDashboard,
  Library,
  ListVideo,
  Settings,
  Workflow,
  Youtube,
} from "lucide-react";
import { EmptyState } from "@/components/shared/states";
import { ChannelsPage } from "@/features/channels/channels-page";
import { Dashboard } from "@/features/dashboard/dashboard";
import { VideosPage } from "@/features/videos/videos-page";

const sections = [
  { title: "Dashboard", path: "/", icon: LayoutDashboard },
  { title: "Channels", path: "/channels", icon: Youtube },
  { title: "Videos", path: "/videos", icon: ListVideo },
  { title: "Processing Jobs", path: "/jobs", icon: Workflow },
  { title: "PDF Library", path: "/library", icon: Library },
  { title: "Settings", path: "/settings", icon: Settings },
];

const futureSections = sections.filter(
  ({ path }) => path !== "/" && path !== "/channels" && path !== "/videos",
);
function Shell() {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-white focus:p-4"
      >
        Skip to content
      </a>
      <aside className="border-b border-border bg-white p-5 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-b-0 lg:p-6">
        <div className="flex items-center gap-3 py-3">
          <div className="rounded-lg bg-primary p-2 text-white">
            <BookOpen size={22} aria-hidden="true" />
          </div>
          <span className="text-sm font-bold tracking-tight">
            ytLecture2slide
          </span>
        </div>
        <p className="eyebrow mt-8 mb-3">WORKSPACE</p>
        <nav
          aria-label="Main navigation"
          className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1"
        >
          {sections.map(({ title, path, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors ${isActive ? "bg-muted font-semibold text-primary" : "text-muted-foreground hover:bg-muted"}`
              }
            >
              <Icon size={18} aria-hidden="true" />
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="mt-8 rounded-lg border border-border p-4 lg:mt-auto">
          <p className="text-xs font-semibold">Local by design</p>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            Built for your own server.
            <br />
            No AI or OCR integration.
          </p>
        </div>
      </aside>
      <div>
        <header className="flex h-16 items-center justify-between border-b border-border px-6 sm:px-10">
          <span className="text-xs text-muted-foreground">
            Lecture workspace
          </span>
          <span className="rounded-full border border-border bg-white px-3 py-1 text-xs">
            Video discovery
          </span>
        </header>
        <main id="main" className="mx-auto max-w-5xl p-6 sm:p-10 lg:p-12">
          <Outlet />
        </main>
        <footer className="px-6 pb-6 text-center text-xs text-muted-foreground">
          ytLecture2slide · Phase 3
        </footer>
      </div>
    </div>
  );
}
export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="/channels" element={<ChannelsPage />} />
        <Route path="/videos" element={<VideosPage />} />
        {futureSections.map(({ title, path }) => (
          <Route
            key={path}
            path={path}
            element={
              <div className="space-y-8">
                <div>
                  <p className="eyebrow">WORKSPACE</p>
                  <h1>{title}</h1>
                </div>
                <EmptyState
                  title={`${title} is not available yet`}
                  description="This section is planned for a later development phase."
                />
              </div>
            }
          />
        ))}
        <Route
          path="*"
          element={
            <EmptyState
              title="Page not found"
              description="Choose a section from the navigation to continue."
            />
          }
        />
      </Route>
    </Routes>
  );
}
