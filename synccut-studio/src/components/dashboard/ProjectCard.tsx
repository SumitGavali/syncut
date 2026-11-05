import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Clock,
  Video,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  MoreVertical,
  Trash2,
  Play,
  FileCode,
} from 'lucide-react';
import { Project, ProjectStatus } from '@/store/useProjectStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface ProjectCardProps {
  project: Project;
  onDelete: (id: string) => void;
}

export const ProjectCard: React.FC<ProjectCardProps> = ({ project, onDelete }) => {
  const navigate = useNavigate();

  const getStatusBadge = (status: ProjectStatus) => {
    switch (status) {
      case 'Ready for Export':
      case 'Synced':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400 border border-emerald-500/20 backdrop-blur-md">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Ready for Export
          </span>
        );
      case 'Syncing':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-400 border border-amber-500/20 backdrop-blur-md">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-spin" />
            Syncing (Active)
          </span>
        );
      case 'Draft':
      default:
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-500/10 px-2.5 py-0.5 text-xs font-medium text-zinc-400 border border-zinc-500/20 backdrop-blur-md">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
            Draft
          </span>
        );
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ y: -4 }}
      transition={{ duration: 0.2 }}
      className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-white/10 bg-[#121217] transition-all duration-300 hover:border-[#00E5FF]/40 hover:shadow-[0_0_30px_rgba(0,229,255,0.12)]"
    >
      {/* Thumbnail area with Hover Overlay */}
      <div className="relative aspect-video w-full overflow-hidden bg-[#181820]">
        <img
          src={project.thumbnailUrl}
          alt={project.name}
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105 opacity-80 group-hover:opacity-100"
        />

        {/* Top Floating Badge */}
        <div className="absolute top-3 left-3 z-10">
          {getStatusBadge(project.status)}
        </div>

        {/* Action Menu (Top Right) */}
        <div className="absolute top-3 right-3 z-10 opacity-80 group-hover:opacity-100 transition-opacity">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-black/60 text-[#ededed] backdrop-blur-md hover:bg-black/80 hover:text-white transition-colors"
              >
                <MoreVertical className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40 border-[#2a2a32] bg-[#141418] text-xs">
              <DropdownMenuItem
                onClick={() => navigate(`/workspace/${project.id}`)}
                className="cursor-pointer gap-2"
              >
                <Play className="h-3.5 w-3.5 text-[#00E5FF]" />
                Open Timeline
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete(project.id)}
                className="cursor-pointer gap-2 text-rose-400 focus:text-rose-400"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete Project
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Hover Overlay Button to Open Workspace */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 backdrop-blur-[2px] transition-opacity duration-200 group-hover:opacity-100">
          <Button
            onClick={() => navigate(`/workspace/${project.id}`)}
            className="h-10 px-5 bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.4)] transition-all transform scale-95 group-hover:scale-100"
          >
            <Play className="h-4 w-4 mr-2 fill-current" />
            Open Workspace
          </Button>
        </div>
      </div>

      {/* Card Body Info */}
      <div className="p-4 flex flex-col justify-between flex-1 space-y-3">
        <div>
          <h3 className="font-semibold text-white tracking-tight text-base group-hover:text-[#00E5FF] transition-colors truncate">
            {project.name}
          </h3>
          <p className="mt-1 text-xs text-[#a1a1aa] line-clamp-1">
            {project.description || 'Multicam audio alignment timeline'}
          </p>
        </div>

        <div className="pt-2 border-t border-white/5 flex items-center justify-between text-[11px] text-[#71717a]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Video className="h-3.5 w-3.5 text-[#00E5FF]" />
              {project.cameraCount} Cams
            </span>
            <span className="flex items-center gap-1 font-mono">
              <Clock className="h-3.5 w-3.5" />
              {project.duration}
            </span>
          </div>

          <span>{project.updatedAt}</span>
        </div>
      </div>
    </motion.div>
  );
};
