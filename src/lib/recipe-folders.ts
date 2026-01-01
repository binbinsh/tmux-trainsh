export type RecipeFolderStatus = "active" | "archived";

export type RecipeFolder = {
  id: string;
  name: string;
  status: RecipeFolderStatus;
  created_at: string;
};

const FOLDERS_KEY = "doppio.recipeFolders.v1";
const ASSIGNMENTS_KEY = "doppio.recipeFolderAssignments.v1";

function safeJsonParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function loadRecipeFolders(): RecipeFolder[] {
  const parsed = safeJsonParse<unknown>(localStorage.getItem(FOLDERS_KEY));
  if (!Array.isArray(parsed)) return [];

  const out: RecipeFolder[] = [];
  for (const item of parsed) {
    if (!item || typeof item !== "object") continue;
    const v = item as Partial<RecipeFolder>;
    if (typeof v.id !== "string" || !v.id.trim()) continue;
    if (typeof v.name !== "string" || !v.name.trim()) continue;
    const status: RecipeFolderStatus = v.status === "archived" ? "archived" : "active";
    out.push({
      id: v.id,
      name: v.name,
      status,
      created_at: typeof v.created_at === "string" ? v.created_at : new Date().toISOString(),
    });
  }
  return out;
}

export function saveRecipeFolders(folders: RecipeFolder[]) {
  localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
}

export function loadRecipeFolderAssignments(): Record<string, string> {
  const parsed = safeJsonParse<unknown>(localStorage.getItem(ASSIGNMENTS_KEY));
  if (!parsed || typeof parsed !== "object") return {};
  const map = parsed as Record<string, unknown>;

  const out: Record<string, string> = {};
  for (const [recipePath, folderId] of Object.entries(map)) {
    if (typeof recipePath !== "string" || !recipePath.trim()) continue;
    if (typeof folderId !== "string" || !folderId.trim()) continue;
    out[recipePath] = folderId;
  }
  return out;
}

export function saveRecipeFolderAssignments(assignments: Record<string, string>) {
  localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(assignments));
}

export function getAssignedFolderId(
  assignments: Record<string, string>,
  recipePath: string
): string | null {
  const v = assignments[recipePath];
  return typeof v === "string" && v.trim() ? v : null;
}

export function setAssignedFolderId(
  assignments: Record<string, string>,
  recipePath: string,
  folderId: string | null
): Record<string, string> {
  const next = { ...assignments };
  if (!folderId) {
    delete next[recipePath];
    return next;
  }
  next[recipePath] = folderId;
  return next;
}

export function renameRecipePathInAssignments(
  assignments: Record<string, string>,
  oldPath: string,
  newPath: string
): Record<string, string> {
  if (oldPath === newPath) return assignments;
  const folderId = assignments[oldPath];
  if (!folderId) return assignments;
  const next = { ...assignments };
  delete next[oldPath];
  next[newPath] = folderId;
  return next;
}

