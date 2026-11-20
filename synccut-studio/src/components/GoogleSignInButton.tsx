import { useState } from 'react';
import axios from 'axios';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/store/useAuthStore';

interface GoogleSignInButtonProps {
  onAuthenticated: () => void;
}

export function GoogleSignInButton({ onAuthenticated }: GoogleSignInButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { loginWithGoogle } = useAuthStore();

  const handleClick = async () => {
    setError('');
    setLoading(true);
    try {
      await loginWithGoogle();
      onAuthenticated();
    } catch (signInError: unknown) {
      if (axios.isAxiosError<{ error?: string }>(signInError)) {
        const errorMsg = signInError.response?.data?.error;
        if (signInError.response?.status === 503 && errorMsg?.includes('GOOGLE_CLIENT_ID')) {
          setError(
            'Google Sign-In requires GOOGLE_CLIENT_ID in your .env file. Please add your Google OAuth client credentials or sign in with your email.',
          );
        } else {
          setError(errorMsg || signInError.message);
        }
      } else {
        setError(signInError instanceof Error ? signInError.message : 'Google sign-in failed.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        disabled={loading}
        onClick={handleClick}
        className="h-10 w-full border-[#2a2a32] bg-[#18181e] font-medium text-white hover:border-[#55555f] hover:bg-[#202027]"
      >
        {loading ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <span aria-hidden="true" className="mr-2 text-base font-bold text-[#4285F4]">G</span>
        )}
        {loading ? 'Waiting for Google...' : 'Continue with Google'}
      </Button>
      {error && (
        <p role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}
    </div>
  );
}
