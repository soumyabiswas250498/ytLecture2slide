import { Outlet, Route, Routes } from "react-router-dom";
import {
  LayoutDashboard,
  Library,
  ListVideo,
  Settings,
  Workflow,
  Youtube,
} from "lucide-react";
import { AppSidebar, type NavSection } from "@/components/shared/app-sidebar";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/states";
import { ChannelsPage } from "@/features/channels/channels-page";
import { Dashboard } from "@/features/dashboard/dashboard";
import { SettingsPage } from "@/features/settings/settings-page";
import { VideosPage } from "@/features/videos/videos-page";

const sections: readonly NavSection[] = [
  { title: "Dashboard", path: "/", icon: LayoutDashboard },
  { title: "Channels", path: "/channels", icon: Youtube },
  { title: "Videos", path: "/videos", icon: ListVideo },
  { title: "Processing Jobs", path: "/jobs", icon: Workflow },
  { title: "PDF Library", path: "/library", icon: Library },
  { title: "Settings", path: "/settings", icon: Settings },
];

const futureSections = sections.filter(
  ({ path }) =>
    path !== "/" &&
    path !== "/channels" &&
    path !== "/videos" &&
    path !== "/settings",
);

function Shell() {
  return (
    <div className="min-h-screen lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-white focus:p-3"
      >
        Skip to content
      </a>
      <AppSidebar sections={sections} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-border bg-white/60 px-4 sm:px-6">
          <span className="text-xs text-muted-foreground">
            Lecture workspace
          </span>
          <span className="rounded-full border border-border bg-white px-2.5 py-0.5 text-xs">
            Full-frame slide processing
          </span>
        </header>
        <main id="main" className="w-full flex-1 p-4 sm:p-5 lg:p-6">
          <Outlet />
        </main>
        <footer className="px-4 pb-4 text-center text-xs text-muted-foreground">
          ytLecture2slide · Local lecture-to-slide workspace
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
        <Route path="/settings" element={<SettingsPage />} />
        {futureSections.map(({ title, path }) => (
          <Route
            key={path}
            path={path}
            element={
              <PageContainer>
                <PageHeader eyebrow="WORKSPACE" title={title} />
                <EmptyState
                  title={`${title} is not available yet`}
                  description="This section is planned for a later development phase."
                />
              </PageContainer>
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
