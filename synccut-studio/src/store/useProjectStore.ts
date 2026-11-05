import { create } from 'zustand';
import { getProjectsApi, createProjectApi, deleteProjectApi, updateProjectApi } from '@/lib/api';

export type ProjectStatus = 'Draft' | 'Syncing' | 'Ready for Export' | 'Synced';

export interface Project {
  id: string;
  name: string;
  description?: string;
  status: ProjectStatus;
  cameraCount: number;
  duration: string;
  updatedAt: string;
  thumbnailUrl: string;
  confidenceScore?: number;
}

interface ProjectState {
  projects: Project[];
  isLoading: boolean;
  activeProjectId: string | null;
  fetchProjects: () => Promise<void>;
  addProject: (name: string, description?: string) => Promise<Project>;
  removeProject: (id: string) => Promise<void>;
  setActiveProject: (id: string | null) => void;
  updateProjectStatus: (id: string, status: ProjectStatus) => Promise<void>;
}

function getStorageKey(): string {
  try {
    const rawUser = localStorage.getItem('synccut_auth_user');
    if (rawUser) {
      const u = JSON.parse(rawUser);
      if (u?.id || u?.email) {
        return `synccut_projects_${u.id || u.email}`;
      }
    }
  } catch {
    // fallback
  }
  return 'synccut_projects_global';
}

function loadCachedProjects(): Project[] {
  try {
    const cached = localStorage.getItem(getStorageKey());
    if (cached) {
      const parsed = JSON.parse(cached);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {
    // fallback
  }
  return [];
}

function saveCachedProjects(projects: Project[]) {
  try {
    localStorage.setItem(getStorageKey(), JSON.stringify(projects));
  } catch {
    // ignore storage limit
  }
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  isLoading: false,
  activeProjectId: null,

  fetchProjects: async () => {
    set({ isLoading: true });
    try {
      const remote = await getProjectsApi();
      if (Array.isArray(remote)) {
        set({ projects: remote, isLoading: false });
        saveCachedProjects(remote);
        return;
      }
    } catch {
      // Offline fallback: keep local cache
      set({ projects: loadCachedProjects(), isLoading: false });
    }
  },

  addProject: async (name: string, description?: string) => {
    const newProj: Project = {
      id: `proj-${Date.now().toString(36)}`,
      name,
      description: description || 'New multicam editing timeline session',
      status: 'Draft',
      cameraCount: 2,
      duration: '00:00:00',
      updatedAt: 'Just now',
      thumbnailUrl: 'https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=640&q=80',
      confidenceScore: 1.0,
    };

    const updated = [newProj, ...get().projects];
    set({ projects: updated });
    saveCachedProjects(updated);

    // Persist to backend database for the logged-in user
    try {
      await createProjectApi(newProj);
    } catch {
      // cached locally
    }

    return newProj;
  },

  removeProject: async (id: string) => {
    const updated = get().projects.filter((p) => p.id !== id);
    set({ projects: updated });
    saveCachedProjects(updated);

    try {
      await deleteProjectApi(id);
    } catch {
      // cached locally
    }
  },

  setActiveProject: (id: string | null) => {
    set({ activeProjectId: id });
  },

  updateProjectStatus: async (id: string, status: ProjectStatus) => {
    const updated = get().projects.map((p) => (p.id === id ? { ...p, status, updatedAt: 'Just now' } : p));
    set({ projects: updated });
    saveCachedProjects(updated);

    try {
      await updateProjectApi(id, { status });
    } catch {
      // cached locally
    }
  },
}));
