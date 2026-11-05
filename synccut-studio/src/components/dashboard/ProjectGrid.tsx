import React from 'react';
import { Project } from '@/store/useProjectStore';
import { ProjectCard } from './ProjectCard';
import { Plus, Film } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ProjectGridProps {
  projects: Project[];
  onNewProject: () => void;
  onDeleteProject: (id: string) => void;
}

export const ProjectGrid: React.FC<ProjectGridProps> = ({
  projects,
  onNewProject,
  onDeleteProject,
}) => {
  if (projects.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[#2a2a32] bg-[#121217]/50 p-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#00E5FF]/10 text-[#00E5FF] border border-[#00E5FF]/20 mb-4">
          <Film className="h-7 w-7" />
        </div>
        <h3 className="text-lg font-bold text-white">No Projects Found</h3>
        <p className="mt-1 text-xs text-[#a1a1aa] max-w-sm">
          Create a multicam project timeline or import your camera files to begin graph audio alignment.
        </p>
        <Button
          onClick={onNewProject}
          className="mt-6 bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.25)]"
        >
          <Plus className="h-4 w-4 mr-1.5" />
          Create First Project
        </Button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          onDelete={onDeleteProject}
        />
      ))}
    </div>
  );
};
