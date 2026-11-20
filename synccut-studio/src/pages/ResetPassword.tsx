import { useState } from 'react';
import axios from 'axios';
import { ArrowLeft, Layers, Loader2, Lock } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { resetPasswordApi } from '@/lib/api';

export default function ResetPassword() {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [complete, setComplete] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const hashSearch = window.location.hash.includes('?')
    ? new URLSearchParams(window.location.hash.split('?')[1])
    : null;
  const token =
    new URLSearchParams(location.search).get('token') ||
    hashSearch?.get('token') ||
    new URLSearchParams(window.location.search).get('token') ||
    '';

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (password.length < 8) {
      setError('Your password must be at least 8 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('The passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      await resetPasswordApi(token, password);
      setComplete(true);
    } catch (resetError: unknown) {
      if (axios.isAxiosError<{ error?: string }>(resetError)) {
        setError(resetError.response?.data?.error || resetError.message);
      } else {
        setError(resetError instanceof Error ? resetError.message : 'Password reset failed.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#0a0a0c] px-4 py-12 text-white">
      <div className="pointer-events-none absolute left-1/2 top-1/4 h-[350px] w-[550px] -translate-x-1/2 rounded-full bg-[#00E5FF]/10 blur-[140px]" />
      <section className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-[#121216]/90 p-8 shadow-2xl backdrop-blur-2xl">
        <div className="mb-7 flex flex-col items-center space-y-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[#00E5FF]/30 bg-[#00E5FF]/10 text-[#00E5FF]">
            <Layers className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">
            {complete ? 'Password updated' : 'Choose a new password'}
          </h1>
          <p className="max-w-xs text-xs leading-relaxed text-[#a1a1aa]">
            {complete
              ? 'Your SyncCut Studio password has been changed. Sign in with your new password.'
              : 'Use at least 8 characters for your new password.'}
          </p>
        </div>

        {complete ? (
          <Button
            type="button"
            onClick={() => navigate('/login', { replace: true })}
            className="h-10 w-full bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff]"
          >
            Back to sign in
          </Button>
        ) : !token ? (
          <div className="space-y-4">
            <p role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              This password reset link is invalid or expired. Request a new one from the sign-in screen.
            </p>
            <Button
              type="button"
              onClick={() => navigate('/login', { replace: true })}
              variant="outline"
              className="w-full border-[#2a2a32] text-white hover:bg-white/5"
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to sign in
            </Button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block space-y-1.5">
              <span className="flex items-center gap-1.5 text-xs font-medium text-[#a1a1aa]">
                <Lock className="h-3.5 w-3.5 text-[#71717a]" />
                New password
              </span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
                className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2.5 text-sm text-white outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="flex items-center gap-1.5 text-xs font-medium text-[#a1a1aa]">
                <Lock className="h-3.5 w-3.5 text-[#71717a]" />
                Confirm new password
              </span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
                className="w-full rounded-lg border border-[#2a2a32] bg-[#18181e] px-3.5 py-2.5 text-sm text-white outline-none transition focus:border-[#00E5FF] focus:ring-1 focus:ring-[#00E5FF]"
              />
            </label>
            {error && (
              <p role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            )}
            <Button
              type="submit"
              disabled={loading}
              className="h-10 w-full bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff]"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Update Password'}
            </Button>
          </form>
        )}
      </section>
    </main>
  );
}
