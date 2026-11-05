import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Layers, Loader2, Lock, Mail, User as UserIcon, ArrowLeft } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';

export default function Login() {
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const { login } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const destination = location.state?.from?.pathname || '/dashboard';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;

    setError('');
    setLoading(true);
    try {
      await login(email, isSignUp ? name : undefined, password, isSignUp);
      navigate(destination, { replace: true });
    } catch (loginError: any) {
      setError(
        loginError?.response?.data?.error ||
        loginError?.message ||
        'Could not verify your account. Check your credentials and that the SyncCut server is running.',
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center bg-[#0a0a0c] px-4 py-12 overflow-hidden selection:bg-[#00E5FF]/20 selection:text-[#00E5FF]">
      {/* Background ambient lighting */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[350px] bg-[#00E5FF]/10 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-[300px] h-[300px] bg-cyan-900/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Back to Home Button */}
      <div className="absolute top-6 left-6 z-20">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate('/')}
          className="text-[#a1a1aa] hover:text-[#00E5FF] hover:bg-white/5 flex items-center gap-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to SyncCut
        </Button>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-[#121216]/90 p-8 shadow-2xl backdrop-blur-2xl"
      >
        <div className="text-center flex flex-col items-center space-y-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] shadow-[0_0_20px_rgba(0,229,255,0.25)]">
            <Layers className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            {isSignUp ? 'Create your Studio Account' : 'Welcome to SyncCut Studio'}
          </h1>
          <p className="text-xs text-[#a1a1aa] max-w-xs leading-relaxed">
            {isSignUp
              ? 'Join professional video editors syncing multicam timelines in sub-frame record time.'
              : 'Sign in to access your projects, timeline sessions, and AI export pipelines.'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          {isSignUp && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[#a1a1aa] flex items-center gap-1.5">
                <UserIcon className="h-3.5 w-3.5 text-[#71717a]" />
                Full Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Alex Rivera"
                required
                className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2.5 text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[#a1a1aa] flex items-center gap-1.5">
              <Mail className="h-3.5 w-3.5 text-[#71717a]" />
              Work Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="editor@studio.com"
              required
              autoComplete="email"
              className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2.5 text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <label className="font-medium text-[#a1a1aa] flex items-center gap-1.5">
                <Lock className="h-3.5 w-3.5 text-[#71717a]" />
                Password
              </label>
              {!isSignUp && (
                <span className="text-[#00E5FF] hover:underline cursor-pointer">
                  Forgot password?
                </span>
              )}
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isSignUp ? 'new-password' : 'current-password'}
              minLength={8}
              placeholder="••••••••••••"
              required
              className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2.5 text-sm text-white placeholder-[#71717a] outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
            />
          </div>

          {error && (
            <p role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          )}

          <Button
            type="submit"
            disabled={loading}
            className="w-full h-10 mt-3 bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff] transition-all duration-200 shadow-[0_0_20px_rgba(0,229,255,0.25)]"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isSignUp ? (
              'Create Account'
            ) : (
              'Sign In to Dashboard'
            )}
          </Button>

        </form>

        <div className="mt-6 text-center text-xs text-[#71717a]">
          {isSignUp ? (
            <p>
              Already registered?{' '}
              <button
                type="button"
                onClick={() => setIsSignUp(false)}
                className="font-medium text-[#00E5FF] hover:underline"
              >
                Sign in
              </button>
            </p>
          ) : (
            <p>
              Need a studio license?{' '}
              <button
                type="button"
                onClick={() => setIsSignUp(true)}
                className="font-medium text-[#00E5FF] hover:underline"
              >
                Sign up free
              </button>
            </p>
          )}
        </div>
      </motion.div>
    </div>
  );
}
