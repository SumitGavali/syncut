import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Plus,
  Layers,
  Search,
  SlidersHorizontal,
  LogOut,
  Sparkles,
  Shield,
  Film,
  Zap,
} from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { useProjectStore } from '@/store/useProjectStore';
import { ProjectGrid } from '@/components/dashboard/ProjectGrid';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';

export default function Dashboard() {
  const { user, logout } = useAuthStore();
  const { projects, addProject, removeProject, fetchProjects } = useProjectStore();
  const navigate = useNavigate();

  const [searchQuery, setSearchQuery] = useState('');
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectDesc, setProjectDesc] = useState('');

  useEffect(() => {
    fetchProjects();
  }, [user?.id, fetchProjects]);

  const filteredProjects = projects.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (p.description && p.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );
  const projectsNeedingReview = projects.filter(
    (project) => project.status !== 'Ready for Export' && project.status !== 'Synced',
  ).length;

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectName.trim()) return;

    const newProj = await addProject(projectName.trim(), projectDesc.trim());
    setProjectName('');
    setProjectDesc('');
    setNewProjectOpen(false);
    toast.success(`Project "${newProj.name}" created.`);
    navigate(`/workspace/${newProj.id}`);
  };

  const handleDeleteProject = (id: string) => {
    removeProject(id);
    toast.info('Project removed from dashboard.');
  };

  const handleLogout = () => {
    logout();
    navigate('/');
    toast.info('Signed out of SyncCut Studio.');
  };

  return (
    <div className="min-h-screen bg-[#0a0a0c] text-[#ededed] flex flex-col selection:bg-[#00E5FF]/20 selection:text-[#00E5FF]">
      {/* Ambient background glow */}
      <div className="absolute top-0 right-1/4 w-[600px] h-[350px] bg-[#00E5FF]/5 blur-[150px] rounded-full pointer-events-none" />

      {/* Top Bar Navigation */}
      <header className="sticky top-0 z-30 border-b border-white/5 bg-[#0a0a0c]/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Brand Logo */}
          <div className="flex items-center gap-3">
            <div
              onClick={() => navigate('/dashboard')}
              className="flex items-center gap-2 cursor-pointer group"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00E5FF]/10 border border-[#00E5FF]/30 transition-all group-hover:border-[#00E5FF]">
                <Layers className="h-5 w-5 text-[#00E5FF]" />
              </div>
              <span className="text-xl font-bold tracking-tight text-white">
                SyncCut <span className="text-[#00E5FF]">Studio</span>
              </span>
            </div>
            <span className="hidden sm:inline-block h-4 w-px bg-white/10 mx-2" />
            <span className="hidden sm:inline-block text-xs text-[#71717a] font-mono">
              PROJECT DASHBOARD
            </span>
          </div>

          {/* User Profile, Plan Status & New Project CTA */}
          <div className="flex items-center gap-4">
            {/* Plan Status Pill */}
            <div className="hidden sm:flex items-center gap-1.5 rounded-full border border-[#00E5FF]/30 bg-[#00E5FF]/10 px-3 py-1 text-xs font-semibold text-[#00E5FF] shadow-[0_0_15px_rgba(0,229,255,0.15)]">
              <Sparkles className="h-3.5 w-3.5" />
              <span>{user?.plan || 'Pro Plan'}</span>
            </div>

            {/* New Project Button */}
            <Button
              onClick={() => setNewProjectOpen(true)}
              className="bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.25)] h-9 px-4 text-xs sm:text-sm"
            >
              <Plus className="h-4 w-4 mr-1.5" />
              New Project
            </Button>

            {/* User Avatar Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="rounded-full ring-2 ring-transparent transition hover:ring-[#00E5FF]/50 focus:outline-none"
                >
                  <Avatar className="h-9 w-9 border border-white/10">
                    <AvatarImage src={user?.avatarUrl} alt={user?.name} />
                    <AvatarFallback>{user?.name?.[0] || 'U'}</AvatarFallback>
                  </Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 border-[#2a2a32] bg-[#141418] text-[#ededed]">
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col space-y-1">
                    <p className="text-sm font-semibold text-white">{user?.name || 'Lead Video Editor'}</p>
                    <p className="text-xs text-[#71717a] truncate">{user?.email || 'editor@synccut.studio'}</p>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => toast.info('Billing settings available in account portal.')}
                  className="cursor-pointer text-xs"
                >
                  <Shield className="h-3.5 w-3.5 mr-2 text-[#00E5FF]" />
                  Subscription: {user?.plan || 'Pro Plan'}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => navigate('/')}
                  className="cursor-pointer text-xs"
                >
                  <Film className="h-3.5 w-3.5 mr-2" />
                  Product Features
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleLogout}
                  className="cursor-pointer text-xs text-rose-400 focus:text-rose-400"
                >
                  <LogOut className="h-3.5 w-3.5 mr-2" />
                  Sign Out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      {/* Main Dashboard Content */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Welcome Banner */}
        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/5 pb-6"
        >
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Projects & Sessions
            </h1>
            <p className="mt-1 text-sm text-[#a1a1aa]">
              Manage multicam timelines, review measured offsets and sync states, and launch the editor workspace.
            </p>
          </div>

          {/* Search Bar */}
          <div className="flex items-center gap-3">
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#71717a]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search projects..."
                className="w-full rounded-lg border border-[#2a2a32] bg-[#141418] pl-9 pr-3.5 py-2 text-xs sm:text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
              />
            </div>
          </div>
        </motion.div>

        {/* Quick Stats overview */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="rounded-xl border border-white/5 bg-[#121217] p-4">
            <span className="text-[11px] text-[#71717a] font-medium uppercase tracking-wider">Active Projects</span>
            <p className="text-2xl font-bold text-white mt-1">{projects.length}</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-[#121217] p-4">
            <span className="text-[11px] text-[#71717a] font-medium uppercase tracking-wider">Ready for Export</span>
            <p className="text-2xl font-bold text-emerald-400 mt-1">
              {projects.filter((p) => p.status === 'Ready for Export' || p.status === 'Synced').length}
            </p>
          </div>
          <div className="rounded-xl border border-white/5 bg-[#121217] p-4">
            <span className="text-[11px] text-[#71717a] font-medium uppercase tracking-wider">Projects Needing Review</span>
            <p className="text-2xl font-bold text-[#00E5FF] mt-1">{projectsNeedingReview}</p>
          </div>
          <div className="rounded-xl border border-white/5 bg-[#121217] p-4">
            <span className="text-[11px] text-[#71717a] font-medium uppercase tracking-wider">Time Saved</span>
            <p className="text-2xl font-bold text-white mt-1">—</p>
          </div>
        </div>

        {/* Projects Grid Section */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[#a1a1aa]">
              Recent Multi-Cam Timelines
            </h2>
            <span className="text-xs text-[#71717a]">
              Showing {filteredProjects.length} of {projects.length}
            </span>
          </div>

          <ProjectGrid
            projects={filteredProjects}
            onNewProject={() => setNewProjectOpen(true)}
            onDeleteProject={handleDeleteProject}
          />
        </section>
      </main>

      {/* New Project Dialog */}
      <Dialog open={newProjectOpen} onOpenChange={setNewProjectOpen}>
        <DialogContent className="sm:max-w-md border border-[#2a2a32] bg-[#121216] text-[#ededed]">
          <form onSubmit={handleCreateProject}>
            <DialogHeader className="space-y-2">
              <DialogTitle className="text-lg font-bold text-white">Create New Multicam Project</DialogTitle>
              <DialogDescription className="text-xs text-[#a1a1aa]">
                Initialize an audio cross-correlation session. You can drop multi-angle video stems inside the workspace.
              </DialogDescription>
            </DialogHeader>

            <div className="my-5 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#a1a1aa]">Project Name</label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g. Austin City Limits Live - Multicam"
                  required
                  autoFocus
                  className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2 text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#a1a1aa]">Notes or Camera Stems (Optional)</label>
                <textarea
                  value={projectDesc}
                  onChange={(e) => setProjectDesc(e.target.value)}
                  placeholder="3x Sony FX3 with master boom mic on channel 1"
                  rows={3}
                  className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2 text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
                />
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setNewProjectOpen(false)}
                className="text-[#a1a1aa] hover:text-white"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                className="bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff]"
              >
                Create & Open Workspace
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
