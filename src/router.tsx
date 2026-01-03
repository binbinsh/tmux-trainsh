import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
import { RootLayout } from "./components/layout/RootLayout";

// Pages
import { HostListPage } from "./pages/hosts";
import { SavedHostDetailPage, VastHostDetailPage } from "./pages/host-detail";
import { SettingsPage } from "./pages/settings";
import { ColabPage } from "./pages/colab";
import { JobPage } from "./pages/job";
import { TerminalPage } from "./pages/terminal";
import { StoragePage } from "./pages/storage";
import { FileBrowserPage } from "./pages/file-browser";
import { SkillsPage } from "./pages/skills";
import { SkillEditorPage } from "./pages/skill-editor";

const rootRoute = createRootRoute({
  component: RootLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/terminal", search: { connectHostId: undefined, connectVastInstanceId: undefined, connectLabel: undefined } });
  },
});

// Host routes
const hostsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/hosts",
  component: HostListPage,
});

const hostDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/hosts/$id",
  component: SavedHostDetailPage,
});

const vastHostDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/hosts/vast/$id",
  component: VastHostDetailPage,
});

const hostNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/hosts/new",
  component: () => {
    // Redirect to hosts page with modal open
    return <HostListPage />;
  },
});

// Legacy session routes - redirect to skills
const sessionsRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sessions",
  beforeLoad: () => {
    throw redirect({ to: "/skills" });
  },
});

const tasksRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks/new",
  beforeLoad: () => {
    throw redirect({ to: "/skills" });
  },
});

// Legacy recipes route - redirect to skills
const recipesRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes",
  beforeLoad: () => {
    throw redirect({ to: "/skills" });
  },
});

// Legacy routes
const colabRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/colab",
  component: ColabPage,
});

const jobRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/job",
  component: JobPage,
});

const terminalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/terminal",
  validateSearch: (search: Record<string, unknown>) => ({
    connectHostId: typeof search.connectHostId === "string" ? search.connectHostId : undefined,
    connectVastInstanceId:
      typeof search.connectVastInstanceId === "string" ? search.connectVastInstanceId : undefined,
    connectLabel: typeof search.connectLabel === "string" ? search.connectLabel : undefined,
  }),
  component: TerminalPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});

// Storage routes
const storageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/storage",
  component: StoragePage,
});

const storageBrowseRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/storage/$id",
  component: FileBrowserPage,
});

// Skill routes
const skillsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/skills",
  component: SkillsPage,
});

const skillEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/skills/$path",
  component: SkillEditorPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  // Host routes
  hostsRoute,
  hostNewRoute,
  hostDetailRoute,
  vastHostDetailRoute,
  // Skill routes
  skillsRoute,
  skillEditorRoute,
  // Storage routes
  storageRoute,
  storageBrowseRoute,
  // Legacy redirects
  sessionsRedirectRoute,
  tasksRedirectRoute,
  recipesRedirectRoute,
  // Legacy routes
  colabRoute,
  jobRoute,
  terminalRoute,
  settingsRoute,
]);

export const router = createRouter({
  routeTree,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
