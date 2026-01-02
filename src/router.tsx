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
import { RecipesPage } from "./pages/recipes";
import { RecipeEditorPage } from "./pages/recipe-editor";

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

// Legacy session routes - redirect to recipes
const sessionsRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sessions",
  beforeLoad: () => {
    throw redirect({ to: "/recipes" });
  },
});

const tasksRedirectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks/new",
  beforeLoad: () => {
    throw redirect({ to: "/recipes" });
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

// Recipe routes
const recipesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes",
  component: RecipesPage,
});

const recipeEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/$path",
  component: RecipeEditorPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  // Host routes
  hostsRoute,
  hostNewRoute,
  hostDetailRoute,
  vastHostDetailRoute,
  // Recipe routes
  recipesRoute,
  recipeEditorRoute,
  // Storage routes
  storageRoute,
  storageBrowseRoute,
  // Legacy redirects
  sessionsRedirectRoute,
  tasksRedirectRoute,
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
