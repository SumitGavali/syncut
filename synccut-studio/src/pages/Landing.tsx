import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, Link } from 'react-router-dom';
import {
  GitMerge,
  ShieldCheck,
  Cpu,
  ArrowRight,
  Play,
  CheckCircle2,
  Sparkles,
  Zap,
  Layers,
  ChevronRight,
  Sliders,
  AudioWaveform,
  Film,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Navbar } from '@/components/layout/Navbar';
import { Footer } from '@/components/layout/Footer';
import { LoginDialog } from '@/components/LoginDialog';
import { useAuthStore } from '@/store/useAuthStore';

export default function Landing() {
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('signup');
  const { isAuthenticated } = useAuthStore();
  const navigate = useNavigate();

  const handleOpenAuth = (mode: 'login' | 'signup') => {
    setAuthMode(mode);
    setAuthDialogOpen(true);
  };

  const handleCtaClick = () => {
    if (isAuthenticated) {
      navigate('/dashboard');
    } else {
      handleOpenAuth('signup');
    }
  };

  return (
    <div className="relative min-h-screen bg-[#0a0a0c] text-[#ededed] overflow-x-hidden selection:bg-[#00E5FF]/20 selection:text-[#00E5FF]">
      {/* Background Glow Orbs */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[550px] bg-[#00E5FF]/10 blur-[160px] rounded-full pointer-events-none" />
      <div className="absolute top-[800px] right-[-100px] w-[500px] h-[500px] bg-cyan-950/20 blur-[140px] rounded-full pointer-events-none" />
      <div className="absolute top-[1800px] left-[-150px] w-[600px] h-[600px] bg-[#00E5FF]/5 blur-[180px] rounded-full pointer-events-none" />

      {/* Grid Overlay */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] pointer-events-none" />

      {/* Navbar */}
      <Navbar onOpenAuth={handleOpenAuth} />

      {/* Hero Section */}
      <section className="relative pt-24 pb-20 md:pt-32 md:pb-32 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className="text-center max-w-4xl mx-auto space-y-6"
        >
          {/* Badge */}
          <div className="inline-flex items-center gap-2 rounded-full border border-[#00E5FF]/30 bg-[#00E5FF]/10 px-4 py-1.5 text-xs font-semibold text-[#00E5FF] shadow-[0_0_20px_rgba(0,229,255,0.2)]">
            <Sparkles className="h-3.5 w-3.5 animate-pulse" />
            <span>Next-Gen Audio-Visual Multicam Synchronizer</span>
            <span className="h-1 w-1 rounded-full bg-[#00E5FF]" />
            <span className="text-white/80">Sub-Millisecond Offset Math</span>
          </div>

          {/* Headline */}
          <h1 className="text-4xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight text-white leading-[1.08]">
            Sync with <span className="cyan-gradient-text">Evidence.</span> <br />
            Edit with <span className="text-[#00E5FF] drop-shadow-[0_0_35px_rgba(0,229,255,0.4)]">Confidence.</span>
          </h1>

          {/* Subtext */}
          <p className="text-base sm:text-xl text-[#a1a1aa] max-w-2xl mx-auto leading-relaxed">
            Eliminate tedious multicam drift, mismatched sample rates, and noisy scratch audio.
            SyncCut resolves global graph alignment with mathematical certainty and builds AI rough cuts in minutes.
          </p>

          {/* CTA & Actions */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
            <Button
              onClick={handleCtaClick}
              size="default"
              className="w-full sm:w-auto h-12 px-8 text-base font-semibold bg-[#00E5FF] text-[#04181c] hover:bg-[#33ecff] shadow-[0_0_30px_rgba(0,229,255,0.4)] transition-all transform hover:-translate-y-0.5"
            >
              Start Editing Free
              <ArrowRight className="h-5 w-5 ml-2" />
            </Button>
            <Button
              variant="outline"
              size="default"
              onClick={() => handleOpenAuth('login')}
              className="w-full sm:w-auto h-12 px-7 text-base border-white/10 bg-white/5 text-[#ededed] hover:border-[#00E5FF]/40 hover:bg-white/10"
            >
              <Play className="h-4 w-4 mr-2 fill-[#00E5FF] text-[#00E5FF]" />
              Sign In
            </Button>
          </div>

          {/* Trust stats */}
          <div className="pt-10 flex flex-wrap items-center justify-center gap-8 text-xs text-[#71717a]">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-[#00E5FF]" />
              <span>Tested on 4K/6K ProRes & BRAW</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-[#00E5FF]" />
              <span>Celery Distributed Async Queue</span>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-[#00E5FF]" />
              <span>Native FCPXML & AAF Timeline Exports</span>
            </div>
          </div>
        </motion.div>

        {/* Hero Interactive Workspace Preview Card */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2, ease: 'easeOut' }}
          className="mt-14 relative rounded-2xl p-1 bg-gradient-to-b from-[#00E5FF]/30 via-white/5 to-transparent shadow-[0_0_50px_rgba(0,229,255,0.15)]"
        >
          <div className="rounded-xl overflow-hidden border border-white/10 bg-[#0e0e13]/90 backdrop-blur-2xl">
            {/* Window Topbar */}
            <div className="flex items-center justify-between border-b border-white/5 px-4 py-3 bg-[#14141a]/90">
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded-full bg-[#ff5f56]" />
                <div className="h-3 w-3 rounded-full bg-[#ffbd2e]" />
                <div className="h-3 w-3 rounded-full bg-[#27c93f]" />
                <span className="ml-3 font-mono text-xs text-[#71717a]">
                  synccut-engine // session_a891f // 3x Multi-Angle Graph
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/20">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Demo · Sync Locked
                </span>
              </div>
            </div>

            {/* Visual Studio mockup */}
            <div className="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Multiview Mockup */}
              <div className="lg:col-span-2 space-y-3">
                <div className="grid grid-cols-2 gap-3 h-64 sm:h-80">
                  <div className="relative rounded-lg overflow-hidden border border-[#00E5FF]/40 bg-[#16161d]">
                    <img
                      src="https://images.unsplash.com/photo-1590602847861-f357a9332bbc?auto=format&fit=crop&w=640&q=80"
                      alt="Host Cam"
                      className="w-full h-full object-cover opacity-85"
                    />
                    <div className="absolute top-2 left-2 bg-black/70 px-2 py-0.5 rounded text-[10px] font-mono text-[#00E5FF] border border-[#00E5FF]/30">
                      CAM A • MASTER [HOST]
                    </div>
                    <div className="absolute bottom-2 right-2 bg-emerald-500/20 text-emerald-300 text-[10px] font-mono px-1.5 py-0.5 rounded border border-emerald-500/30">
                      ACTIVE SPEAKER
                    </div>
                  </div>
                  <div className="relative rounded-lg overflow-hidden border border-white/10 bg-[#16161d]">
                    <img
                      src="https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=640&q=80"
                      alt="Guest Cam"
                      className="w-full h-full object-cover opacity-75"
                    />
                    <div className="absolute top-2 left-2 bg-black/70 px-2 py-0.5 rounded text-[10px] font-mono text-[#ededed] border border-white/10">
                      CAM B • GUEST [OFFSET: +14.238s]
                    </div>
                  </div>
                </div>

                {/* Simulated Audio Waveform Bar */}
                <div className="h-20 rounded-lg border border-white/10 bg-[#121217] p-3 flex flex-col justify-between">
                  <div className="flex items-center justify-between text-[11px] text-[#a1a1aa] font-mono">
                    <span className="flex items-center gap-1.5 text-[#00E5FF]">
                      <AudioWaveform className="h-3.5 w-3.5" />
                      Cross-Correlation FFT Waveform Peak Align
                    </span>
                    <span>00:14:32:18 / 01:14:28:00</span>
                  </div>
                  <div className="w-full h-8 flex items-center gap-0.5 overflow-hidden">
                    {Array.from({ length: 64 }).map((_, i) => (
                      <div
                        key={i}
                        className={`flex-1 rounded-sm transition-all ${
                          i > 24 && i < 40
                            ? 'bg-[#00E5FF] opacity-90'
                            : 'bg-[#2a2a38] opacity-60'
                        }`}
                        style={{ height: `${Math.max(15, ((i * 37) % 85) + 10)}%` }}
                      />
                    ))}
                  </div>
                </div>
              </div>

              {/* Engine Telemetry Side */}
              <div className="rounded-lg border border-white/10 bg-[#14141a] p-4 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between pb-3 border-b border-white/5">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
                      Sync Intelligence
                    </h3>
                    <span className="text-[10px] text-[#00E5FF] font-mono">Graph Solver</span>
                  </div>

                  <div className="mt-4 space-y-3">
                    <div className="p-2.5 rounded bg-white/5 border border-white/5">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[#a1a1aa]">Pairwise Alignment</span>
                        <span className="text-emerald-400 font-mono font-medium">Aligned</span>
                      </div>
                    </div>

                    <div className="p-2.5 rounded bg-white/5 border border-white/5">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[#a1a1aa]">Calculated Drift</span>
                        <span className="text-[#00E5FF] font-mono font-medium">Measured per camera</span>
                      </div>
                    </div>

                    <div className="p-2.5 rounded bg-white/5 border border-white/5">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[#a1a1aa]">AI Active Cuts</span>
                        <span className="text-white font-mono font-medium">Optional suggestions</span>
                      </div>
                      <p className="text-[11px] text-[#71717a] mt-1">
                        Build the program lane yourself or review suggested edits.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="pt-4 border-t border-white/5">
                  <Button
                    onClick={handleCtaClick}
                    className="w-full bg-[#00E5FF]/10 text-[#00E5FF] border border-[#00E5FF]/30 hover:bg-[#00E5FF] hover:text-[#04181c] transition-all font-semibold"
                  >
                    Open Live Timeline
                    <ArrowRight className="h-4 w-4 ml-1.5" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Deliverable 1: Features Section */}
      <section id="features" className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto border-t border-white/5">
        <div className="text-center max-w-3xl mx-auto space-y-4 mb-16">
          <h2 className="text-xs uppercase tracking-widest text-[#00E5FF] font-bold">
            Architected for Editors
          </h2>
          <h3 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Stop guessing audio slips. <br />
            Let graph theory lock your multicam.
          </h3>
          <p className="text-base text-[#a1a1aa]">
            Traditional NLEs guess offsets linearly. SyncCut builds an interconnected graph of all camera pairs to resolve the true timeline mathematically.
          </p>
        </div>

        {/* 3 Core Highlight Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Card 1: Global Graph Sync */}
          <motion.div
            whileHover={{ y: -6 }}
            transition={{ duration: 0.2 }}
            className="group relative rounded-2xl border border-white/10 bg-[#121216]/80 p-8 backdrop-blur-xl transition-all duration-300 hover:border-[#00E5FF]/40 hover:shadow-[0_0_35px_rgba(0,229,255,0.15)] flex flex-col justify-between"
          >
            <div className="space-y-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] transition-transform duration-300 group-hover:scale-110 group-hover:shadow-[0_0_20px_rgba(0,229,255,0.3)]">
                <GitMerge className="h-7 w-7" />
              </div>
              <h4 className="text-xl font-bold text-white group-hover:text-[#00E5FF] transition-colors">
                1. Global Graph Sync
              </h4>
              <p className="text-sm text-[#a1a1aa] leading-relaxed">
                Connects 2 to 20+ asynchronous cameras. Even if Camera C cannot hear Camera A, SyncCut routes alignment through intermediate audio matches with zero drift.
              </p>
            </div>
            <div className="mt-6 pt-4 border-t border-white/5 flex items-center text-xs font-semibold text-[#00E5FF]">
              <span>Cycle-consistent spanning tree</span>
              <ChevronRight className="h-4 w-4 ml-1 transition-transform group-hover:translate-x-1" />
            </div>
          </motion.div>

          {/* Card 2: Calibrated Confidence Metrics */}
          <motion.div
            whileHover={{ y: -6 }}
            transition={{ duration: 0.2 }}
            className="group relative rounded-2xl border border-white/10 bg-[#121216]/80 p-8 backdrop-blur-xl transition-all duration-300 hover:border-[#00E5FF]/40 hover:shadow-[0_0_35px_rgba(0,229,255,0.15)] flex flex-col justify-between"
          >
            <div className="space-y-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] transition-transform duration-300 group-hover:scale-110 group-hover:shadow-[0_0_20px_rgba(0,229,255,0.3)]">
                <ShieldCheck className="h-7 w-7" />
              </div>
              <h4 className="text-xl font-bold text-white group-hover:text-[#00E5FF] transition-colors">
                2. Transparent Sync Metrics
              </h4>
              <p className="text-sm text-[#a1a1aa] leading-relaxed">
                Review measured offsets, drift, pairwise consistency, and per-camera sync states before export.
              </p>
            </div>
            <div className="mt-6 pt-4 border-t border-white/5 flex items-center text-xs font-semibold text-[#00E5FF]">
              <span>Audit PDF & Error Margins</span>
              <ChevronRight className="h-4 w-4 ml-1 transition-transform group-hover:translate-x-1" />
            </div>
          </motion.div>

          {/* Card 3: AI Active Speaker Rough Cuts */}
          <motion.div
            whileHover={{ y: -6 }}
            transition={{ duration: 0.2 }}
            className="group relative rounded-2xl border border-white/10 bg-[#121216]/80 p-8 backdrop-blur-xl transition-all duration-300 hover:border-[#00E5FF]/40 hover:shadow-[0_0_35px_rgba(0,229,255,0.15)] flex flex-col justify-between"
          >
            <div className="space-y-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] transition-transform duration-300 group-hover:scale-110 group-hover:shadow-[0_0_20px_rgba(0,229,255,0.3)]">
                <Cpu className="h-7 w-7" />
              </div>
              <h4 className="text-xl font-bold text-white group-hover:text-[#00E5FF] transition-colors">
                3. AI Active Speaker Rough Cuts
              </h4>
              <p className="text-sm text-[#a1a1aa] leading-relaxed">
                Detect who is talking with energy-level speaker diarization. Automatically inserts camera cuts with smart cadence buffers so dialog feels natural and broadcast-ready.
              </p>
            </div>
            <div className="mt-6 pt-4 border-t border-white/5 flex items-center text-xs font-semibold text-[#00E5FF]">
              <span>One-Click FCPXML & AAF Export</span>
              <ChevronRight className="h-4 w-4 ml-1 transition-transform group-hover:translate-x-1" />
            </div>
          </motion.div>
        </div>
      </section>

      {/* Benchmarking Comparison */}
      <section id="benchmark" className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto border-t border-white/5">
        <div className="rounded-2xl border border-white/10 bg-[#111116] p-8 lg:p-12">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#00E5FF]">
                <Zap className="h-4 w-4" />
                <span>BENCHMARK RESULTS</span>
              </div>
              <h3 className="text-2xl sm:text-3xl font-bold text-white">
                10x faster than Premiere Pro or PluralEyes legacy workflows.
              </h3>
              <p className="text-sm text-[#a1a1aa] leading-relaxed">
                Traditional desktop NLEs freeze your editing workstation while re-encoding full-res video files.
                SyncCut streams audio proxies directly into a Celery task queue, computing millisecond cross-correlations in the background.
              </p>

              <div className="pt-2 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white font-medium">SyncCut Studio Cloud Queue (4 Cams)</span>
                  <span className="text-[#00E5FF] font-mono">1 min 14 sec</span>
                </div>
                <div className="w-full bg-[#1e1e24] h-2 rounded-full overflow-hidden">
                  <div className="bg-[#00E5FF] h-full w-[20%]" />
                </div>

                <div className="flex items-center justify-between text-xs pt-2">
                  <span className="text-[#71717a]">Legacy NLE Multi-Camera Clip Generator</span>
                  <span className="text-[#71717a] font-mono">14 min 30 sec</span>
                </div>
                <div className="w-full bg-[#1e1e24] h-2 rounded-full overflow-hidden">
                  <div className="bg-[#71717a] h-full w-[95%]" />
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-[#16161e] p-6 space-y-4">
              <h4 className="text-sm font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                <Film className="h-4 w-4 text-[#00E5FF]" />
                Supported NLE Timelines
              </h4>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-3 rounded-lg border border-white/5 bg-[#121216]">
                  <p className="font-semibold text-white">Final Cut Pro</p>
                  <p className="text-[#71717a]">FCPXML v1.9 - v1.11</p>
                </div>
                <div className="p-3 rounded-lg border border-white/5 bg-[#121216]">
                  <p className="font-semibold text-white">Adobe Premiere Pro</p>
                  <p className="text-[#71717a]">XML / FCPXML Import</p>
                </div>
                <div className="p-3 rounded-lg border border-white/5 bg-[#121216]">
                  <p className="font-semibold text-white">DaVinci Resolve</p>
                  <p className="text-[#71717a]">XML & Multi-Track EDLs</p>
                </div>
                <div className="p-3 rounded-lg border border-white/5 bg-[#121216]">
                  <p className="font-semibold text-white">Avid Media Composer</p>
                  <p className="text-[#71717a]">AAF Composition Stems</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing / Plan Section */}
      <section id="pricing" className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto border-t border-white/5">
        <div className="text-center max-w-2xl mx-auto space-y-3 mb-16">
          <h2 className="text-xs uppercase tracking-widest text-[#00E5FF] font-bold">Simple Pricing</h2>
          <h3 className="text-3xl sm:text-4xl font-extrabold text-white">Built for Freelancers & Studios</h3>
          <p className="text-sm text-[#a1a1aa]">Start free today. Upgrade when you take on heavy multi-angle productions.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Free Tier */}
          <div className="rounded-2xl border border-white/10 bg-[#121216] p-8 flex flex-col justify-between">
            <div className="space-y-4">
              <h4 className="text-lg font-bold text-white">Free Starter</h4>
              <div className="text-3xl font-extrabold text-white">$0 <span className="text-xs text-[#71717a] font-normal">/ month</span></div>
              <p className="text-xs text-[#a1a1aa]">For indie creators testing 2-camera podcasts.</p>
              <ul className="space-y-2.5 text-xs text-[#a1a1aa] pt-2">
                <li className="flex items-center gap-2">✓ 2 Cams per sync session</li>
                <li className="flex items-center gap-2">✓ 30 min max clip length</li>
                <li className="flex items-center gap-2">✓ Standard FCPXML export</li>
              </ul>
            </div>
            <Button
              variant="outline"
              onClick={() => handleOpenAuth('signup')}
              className="mt-8 border-white/10 bg-white/5 text-white hover:border-[#00E5FF]"
            >
              Start Free
            </Button>
          </div>

          {/* Pro Tier (Popular) */}
          <div className="relative rounded-2xl border-2 border-[#00E5FF] bg-[#121216] p-8 flex flex-col justify-between shadow-[0_0_30px_rgba(0,229,255,0.2)]">
            <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 rounded-full bg-[#00E5FF] px-3 py-0.5 text-[11px] font-bold text-[#04181c]">
              MOST POPULAR FOR FREELANCERS
            </div>
            <div className="space-y-4">
              <h4 className="text-lg font-bold text-white">Editor Pro</h4>
              <div className="text-3xl font-extrabold text-white">$24 <span className="text-xs text-[#71717a] font-normal">/ month</span></div>
              <p className="text-xs text-[#a1a1aa]">For professional editors delivering multi-cam client projects.</p>
              <ul className="space-y-2.5 text-xs text-[#ededed] pt-2">
                <li className="flex items-center gap-2 text-[#00E5FF]">✓ Unlimited asynchronous cameras</li>
                <li className="flex items-center gap-2">✓ Global Graph Sync & Drift Compensation</li>
                <li className="flex items-center gap-2">✓ AI Active Speaker Rough Cuts</li>
                <li className="flex items-center gap-2">✓ FCPXML, AAF & PDF Audit Reports</li>
                <li className="flex items-center gap-2">✓ Priority Celery Cloud Queue</li>
              </ul>
            </div>
            <Button
              onClick={() => handleOpenAuth('signup')}
              className="mt-8 bg-[#00E5FF] text-[#04181c] font-semibold hover:bg-[#33ecff] shadow-[0_0_20px_rgba(0,229,255,0.3)]"
            >
              Get Pro Access
            </Button>
          </div>

          {/* Studio Tier */}
          <div className="rounded-2xl border border-white/10 bg-[#121216] p-8 flex flex-col justify-between">
            <div className="space-y-4">
              <h4 className="text-lg font-bold text-white">Studio Team</h4>
              <div className="text-3xl font-extrabold text-white">$79 <span className="text-xs text-[#71717a] font-normal">/ month</span></div>
              <p className="text-xs text-[#a1a1aa]">For production houses and post-production suites.</p>
              <ul className="space-y-2.5 text-xs text-[#a1a1aa] pt-2">
                <li className="flex items-center gap-2">✓ Everything in Pro</li>
                <li className="flex items-center gap-2">✓ 5 Editor Seats & Shared Projects</li>
                <li className="flex items-center gap-2">✓ Dedicated GPU Celery Workers</li>
                <li className="flex items-center gap-2">✓ Custom Webhook & API Access</li>
              </ul>
            </div>
            <Button
              variant="outline"
              onClick={() => handleOpenAuth('signup')}
              className="mt-8 border-white/10 bg-white/5 text-white hover:border-[#00E5FF]"
            >
              Contact Sales
            </Button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <Footer />

      {/* Auth Modal Dialog */}
      <LoginDialog
        open={authDialogOpen}
        onOpenChange={setAuthDialogOpen}
        defaultMode={authMode}
      />
    </div>
  );
}
