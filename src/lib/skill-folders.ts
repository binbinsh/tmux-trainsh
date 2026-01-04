export type SkillFolderStatus = "active" | "archived";

export type SkillFolder = {
  id: string;
  name: string;
  status: SkillFolderStatus;
  created_at: string;
};

const FOLDERS_KEY = "doppio.skillFolders.v1";
const ASSIGNMENTS_KEY = "doppio.skillFolderAssignments.v1";

function safeJsonParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function loadSkillFolders(): SkillFolder[] {
  const parsed = safeJsonParse<unknown>(localStorage.getItem(FOLDERS_KEY));
  if (!Array.isArray(parsed)) return [];

  const out: SkillFolder[] = [];
  for (const item of parsed) {
    if (!item || typeof item !== "object") continue;
    const v = item as Partial<SkillFolder>;
    if (typeof v.id !== "string" || !v.id.trim()) continue;
    if (typeof v.name !== "string" || !v.name.trim()) continue;
    const status: SkillFolderStatus = v.status === "archived" ? "archived" : "active";
    out.push({
      id: v.id,
      name: v.name,
      status,
      created_at: typeof v.created_at === "string" ? v.created_at : new Date().toISOString(),
    });
  }
  return out;
}

export function saveSkillFolders(folders: SkillFolder[]) {
  localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
}

export function loadSkillFolderAssignments(): Record<string, string> {
  const parsed = safeJsonParse<unknown>(localStorage.getItem(ASSIGNMENTS_KEY));
  if (!parsed || typeof parsed !== "object") return {};
  const map = parsed as Record<string, unknown>;

  const out: Record<string, string> = {};
  for (const [skillPath, folderId] of Object.entries(map)) {
    if (typeof skillPath !== "string" || !skillPath.trim()) continue;
    if (typeof folderId !== "string" || !folderId.trim()) continue;
    out[skillPath] = folderId;
  }
  return out;
}

export function saveSkillFolderAssignments(assignments: Record<string, string>) {
  localStorage.setItem(ASSIGNMENTS_KEY, JSON.stringify(assignments));
}

export function getAssignedFolderId(
  assignments: Record<string, string>,
  skillPath: string
): string | null {
  const v = assignments[skillPath];
  return typeof v === "string" && v.trim() ? v : null;
}

export function setAssignedFolderId(
  assignments: Record<string, string>,
  skillPath: string,
  folderId: string | null
): Record<string, string> {
  const next = { ...assignments };
  if (!folderId) {
    delete next[skillPath];
    return next;
  }
  next[skillPath] = folderId;
  return next;
}

export function renameSkillPathInAssignments(
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

