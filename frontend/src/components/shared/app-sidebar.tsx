import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  BookOpen,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";

export interface NavSection {
  title: string;
  path: string;
  icon: LucideIcon;
}

const SIDEBAR_STORAGE_KEY = "ytl2s.sidebar.collapsed";

function readStoredCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeStoredCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  } catch {
    // Ignore storage failures in restricted environments.
  }
}

export function AppSidebar({ sections }: { sections: readonly NavSection[] }) {
  const [collapsed, setCollapsed] = useState<boolean>(readStoredCollapsed);

  useEffect(() => {
    writeStoredCollapsed(collapsed);
  }, [collapsed]);

  return (
    <aside
      data-collapsed={collapsed}
      className={`shrink-0 border-b border-border bg-white p-3 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-b-0 lg:transition-[width] lg:duration-150 ${
        collapsed ? "lg:w-[60px] lg:px-2 lg:py-3" : "lg:w-[220px] lg:p-4"
      }`}
    >
      <div
        className={`flex items-center py-1 ${
          collapsed ? "justify-between lg:justify-center" : "justify-between"
        }`}
      >
        <div className="flex items-center gap-2.5 overflow-hidden">
          <div
            className="shrink-0 rounded-md bg-primary p-1.5 text-white"
            title={collapsed ? "ytLecture2slide" : undefined}
          >
            <BookOpen size={18} aria-hidden="true" />
          </div>
          {!collapsed && (
            <span className="truncate text-sm font-bold tracking-tight">
              ytLecture2slide
            </span>
          )}
        </div>
        {!collapsed && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
            onClick={() => setCollapsed(true)}
            className="hidden h-7 w-7 shrink-0 p-0 text-muted-foreground hover:text-foreground lg:inline-flex"
          >
            <PanelLeftClose size={15} aria-hidden="true" />
          </Button>
        )}
      </div>

      {collapsed && (
        <div className="mt-2 hidden justify-center lg:flex">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Expand sidebar"
            title="Expand sidebar"
            onClick={() => setCollapsed(false)}
            className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
          >
            <PanelLeftOpen size={16} aria-hidden="true" />
          </Button>
        </div>
      )}

      {!collapsed && <p className="eyebrow mt-5 mb-2">WORKSPACE</p>}

      <nav
        aria-label="Main navigation"
        className={`mt-2 grid grid-cols-2 gap-1 sm:grid-cols-3 lg:grid-cols-1 ${
          collapsed ? "lg:mt-3" : "lg:mt-0"
        }`}
      >
        {sections.map(({ title, path, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === "/"}
            aria-label={title}
            title={collapsed ? title : undefined}
            className={({ isActive }) =>
              `flex items-center rounded-md py-2 text-sm transition-colors ${
                collapsed ? "justify-center px-2 lg:px-0" : "gap-2.5 px-2.5"
              } ${
                isActive
                  ? "bg-muted font-semibold text-primary"
                  : "text-muted-foreground hover:bg-muted"
              }`
            }
          >
            <Icon size={16} aria-hidden="true" className="shrink-0" />
            <span className={collapsed ? "lg:sr-only" : "truncate"}>
              {title}
            </span>
          </NavLink>
        ))}
      </nav>

      {!collapsed && (
        <div className="mt-5 hidden rounded-md border border-border p-3 lg:mt-auto lg:block">
          <p className="text-xs font-semibold">Local by design</p>
          <p className="mt-1 text-xs leading-4 text-muted-foreground">
            Built for your own server. No AI or OCR integration.
          </p>
        </div>
      )}
    </aside>
  );
}
