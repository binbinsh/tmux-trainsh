import { createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
import { RootLayout } from "./components/layout/RootLayout";

// Pages
import { DashboardPage } from "./pages/dashboard";
import { HostListPage } from "./pages/hosts";
import { HostDetailPage } from "./pages/host-detail";
import { SettingsPage } from "./pages/settings";
import { VastPage } from "./pages/vast";
import { ColabPage } from "./pages/colab";
import { JobPage } from "./pages/job";
import { TerminalPage } from "./pages/terminal";
import { StoragePage } from "./pages/storage";
import { FileBrowserPage } from "./pages/file-browser";
import { RecipesPage } from "./pages/recipes";
import { RecipeEditorPage } from "./pages/recipe-editor";
import { RecipeExecutionPage } from "./pages/recipe-execution";

const rootRoute = createRootRoute({
  component: RootLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/dashboard" });
  },
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dashboard",
  component: DashboardPage,
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
  component: HostDetailPage,
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
const vastRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/vast",
  component: VastPage,
});

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

const recipeExecutionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/executions/$id",
  component: RecipeExecutionPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  dashboardRoute,
  // Host routes
  hostsRoute,
  hostNewRoute,
  hostDetailRoute,
  // Recipe routes
  recipesRoute,
  recipeExecutionRoute,  // Must be before recipeEditorRoute to match /recipes/executions/$id first
  recipeEditorRoute,
  // Storage routes
  storageRoute,
  storageBrowseRoute,
  // Legacy redirects
  sessionsRedirectRoute,
  tasksRedirectRoute,
  // Legacy routes
  vastRoute,
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
