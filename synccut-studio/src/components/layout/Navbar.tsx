import React from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, Layers, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/store/useAuthStore';

interface NavbarProps {
  onOpenAuth?: (mode: 'login' | 'signup') => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenAuth }) => {
  const { isAuthenticated, user } = useAuthStore();

  return (
    <header className="sticky top-0 z-40 w-full border-b border-white/5 bg-[#0a0a0c]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link to="/" className="flex items-center gap-2 group">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00E5FF]/10 border border-[#00E5FF]/30 transition-all duration-300 group-hover:scale-105 group-hover:border-[#00E5FF] group-hover:shadow-[0_0_15px_rgba(0,229,255,0.4)]">
            <Layers className="h-5 w-5 text-[#00E5FF]" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">
            SyncCut <span className="text-[#00E5FF]">Studio</span>
          </span>
          <span className="hidden sm:inline-flex items-center rounded-full bg-[#00E5FF]/10 px-2 py-0.5 text-[10px] font-medium text-[#00E5FF] border border-[#00E5FF]/20">
            v2.4 PRO
          </span>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-[#a1a1aa]">
          <a href="#features" className="transition-colors hover:text-[#00E5FF]">
            Features
          </a>
          <a href="#benchmark" className="transition-colors hover:text-[#00E5FF]">
            Benchmarking
          </a>
          <a href="#pricing" className="transition-colors hover:text-[#00E5FF]">
            Pricing
          </a>
        </nav>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <Link to="/dashboard">
              <Button className="bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.25)]">
                Go to Dashboard
                <ArrowRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={() => onOpenAuth?.('login')}
                className="text-[#ededed] hover:text-[#00E5FF] hover:bg-white/5"
              >
                Sign In
              </Button>
              <Button
                onClick={() => onOpenAuth?.('signup')}
                className="bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.25)] transition-all"
              >
                Start Free
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
