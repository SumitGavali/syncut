import React from 'react';
import { Layers, Github, Heart } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-white/5 bg-[#0a0a0c] py-12 text-[#a1a1aa]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[#00E5FF]/10 border border-[#00E5FF]/30">
              <Layers className="h-4 w-4 text-[#00E5FF]" />
            </div>
            <span className="text-base font-semibold text-white">
              SyncCut <span className="text-[#00E5FF]">Studio</span>
            </span>
            <span className="text-xs text-[#71717a]">| The Freelance Multi-Camera Intelligence Engine</span>
          </div>

          <div className="flex items-center gap-6 text-sm">
            <Link to="/dashboard" className="hover:text-[#00E5FF] transition-colors">
              App Dashboard
            </Link>
            <a href="#features" className="hover:text-[#00E5FF] transition-colors">
              Engine Specs
            </a>
            <a href="https://github.com/SumitGavali/syncut" target="_blank" rel="noreferrer" className="flex items-center gap-1.5 hover:text-white transition-colors">
              <Github className="h-4 w-4" />
              <span>GitHub</span>
            </a>
          </div>
        </div>

        <div className="mt-8 flex flex-col md:flex-row items-center justify-between border-t border-white/5 pt-6 text-xs text-[#71717a]">
          <p>© 2026 SyncCut Inc. Built for editors who care about sub-frame precision.</p>
          <p className="flex items-center gap-1 mt-2 md:mt-0">
            Engineered with <span className="text-[#00E5FF]">FastAPI</span>, <span className="text-[#00E5FF]">Celery</span> & <span className="text-[#00E5FF]">WebAudio</span>
          </p>
        </div>
      </div>
    </footer>
  );
};
