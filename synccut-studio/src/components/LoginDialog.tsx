import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Layers, Loader2, Lock, Mail, User as UserIcon } from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import { useNavigate } from 'react-router-dom';
import { requestPasswordResetApi } from '@/lib/api';
import { GoogleSignInButton } from '@/components/GoogleSignInButton';

interface LoginDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultMode?: 'login' | 'signup';
}

export const LoginDialog: React.FC<LoginDialogProps> = ({
  open,
  onOpenChange,
  defaultMode = 'login',
}) => {
  const [isSignUp, setIsSignUp] = useState(defaultMode === 'signup');
  const [isForgotPassword, setIsForgotPassword] = useState(false);
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const { login } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    setIsSignUp(defaultMode === 'signup');
    setIsForgotPassword(false);
    setError('');
    setNotice('');
  }, [defaultMode, open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');

    if (isForgotPassword) {
      if (!email.trim()) {
        setError('Please enter your email address to reset your password.');
        return;
      }
      setLoading(true);
      try {
        const response = await requestPasswordResetApi(email.trim());
        if (response.token) {
          onOpenChange(false);
          navigate(`/reset-password?token=${encodeURIComponent(response.token)}`);
          return;
        }
        setNotice(response.message);
      } catch (resetError: any) {
        setError(
          resetError?.response?.data?.error ||
          resetError?.message ||
          'Could not request a password reset. Check that the SyncCut server is running.',
        );
      } finally {
        setLoading(false);
      }
      return;
    }

    if (!email.trim() || !password.trim()) {
      setError('Please enter both your email and password.');
      return;
    }

    setLoading(true);
    try {
      await login(email.trim(), isSignUp ? name.trim() : undefined, password, isSignUp);
      onOpenChange(false);
      navigate('/dashboard');
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px] border border-[#2a2a32] bg-[#121216]/95 backdrop-blur-2xl text-[#ededed] shadow-2xl p-6">
        <DialogHeader className="space-y-2 text-center items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#00E5FF]/10 border border-[#00E5FF]/30 text-[#00E5FF] shadow-[0_0_20px_rgba(0,229,255,0.25)]">
            <Layers className="h-6 w-6" />
          </div>
          <DialogTitle className="text-xl font-bold tracking-tight text-white">
            {isForgotPassword
              ? 'Reset your password'
              : isSignUp
              ? 'Create your Studio Account'
              : 'Welcome to SyncCut Studio'}
          </DialogTitle>
          <DialogDescription className="text-xs text-[#a1a1aa] max-w-xs">
            {isForgotPassword
              ? 'Enter your account email to receive or generate a password reset link.'
              : isSignUp
              ? 'Join professional video editors syncing multicam timelines in minutes.'
              : 'Sign in to access your projects, timeline sessions, and AI export pipelines.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          {isSignUp && !isForgotPassword && (
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

          {!isForgotPassword && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <label className="font-medium text-[#a1a1aa] flex items-center gap-1.5">
                  <Lock className="h-3.5 w-3.5 text-[#71717a]" />
                  Password
                </label>
                {!isSignUp && (
                  <button
                    type="button"
                    onClick={() => {
                      setError('');
                      setNotice('');
                      setIsForgotPassword(true);
                    }}
                    className="text-[#00E5FF] hover:underline"
                  >
                    Forgot password?
                  </button>
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
          )}

          {notice && (
            <p role="status" className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {notice}
            </p>
          )}

          {error && (
            <p role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          )}

          <Button
            type="submit"
            disabled={loading}
            className="w-full h-10 mt-2 bg-[#00E5FF] font-semibold text-[#04181c] hover:bg-[#33ecff] transition-all duration-200 shadow-[0_0_20px_rgba(0,229,255,0.25)]"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isForgotPassword ? (
              'Send Reset Link'
            ) : isSignUp ? (
              'Create Account'
            ) : (
              'Sign In to Dashboard'
            )}
          </Button>
        </form>

        {!isForgotPassword && (
          <>
            <div className="my-4 flex items-center gap-3 text-[10px] uppercase tracking-wider text-[#71717a]">
              <span className="h-px flex-1 bg-white/10" />
              or
              <span className="h-px flex-1 bg-white/10" />
            </div>
            <GoogleSignInButton
              onAuthenticated={() => {
                onOpenChange(false);
                navigate('/dashboard');
              }}
            />
          </>
        )}

        <div className="mt-4 text-center text-xs text-[#71717a]">
          {isForgotPassword ? (
            <p>
              Remembered your password?{' '}
              <button
                type="button"
                onClick={() => {
                  setError('');
                  setNotice('');
                  setIsForgotPassword(false);
                }}
                className="font-medium text-[#00E5FF] hover:underline"
              >
                Back to sign in
              </button>
            </p>
          ) : isSignUp ? (
            <p>
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => {
                  setError('');
                  setNotice('');
                  setIsSignUp(false);
                }}
                className="font-medium text-[#00E5FF] hover:underline"
              >
                Sign in
              </button>
            </p>
          ) : (
            <p>
              Don't have an account yet?{' '}
              <button
                type="button"
                onClick={() => {
                  setError('');
                  setNotice('');
                  setIsSignUp(true);
                }}
                className="font-medium text-[#00E5FF] hover:underline"
              >
                Sign up free
              </button>
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
