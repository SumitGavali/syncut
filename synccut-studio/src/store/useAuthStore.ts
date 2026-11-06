import { create } from 'zustand';
import { loginApi, registerApi, getMeApi, logoutApi } from '@/lib/api';

export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl: string;
  tier: 'free' | 'pro' | 'studio';
  plan: 'Free Plan' | 'Pro Plan' | 'Studio Plan';
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  login: (email: string, name?: string, password?: string, isSignUp?: boolean) => Promise<void>;
  logout: () => void;
  initialize: () => void;
}

const DEFAULT_AVATAR = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&q=80';

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isInitializing: true,

  initialize: async () => {
    const savedToken = localStorage.getItem('synccut_auth_token');
    if (!savedToken) {
      localStorage.removeItem('synccut_auth_user');
      set({ user: null, token: null, isAuthenticated: false, isInitializing: false });
      return;
    }

    try {
      const remoteUser = await getMeApi();
      const userObj: User = {
        id: remoteUser.id,
        name: remoteUser.name,
        email: remoteUser.email,
        avatarUrl: DEFAULT_AVATAR,
        tier: remoteUser.tier || 'free',
        plan: remoteUser.plan || 'Free Plan',
      };
      localStorage.setItem('synccut_auth_user', JSON.stringify(userObj));
      set({
        token: savedToken,
        user: userObj,
        isAuthenticated: true,
        isInitializing: false,
      });
    } catch {
      localStorage.removeItem('synccut_auth_token');
      localStorage.removeItem('synccut_auth_user');
      set({ user: null, token: null, isAuthenticated: false, isInitializing: false });
    }
  },

  login: async (email: string, name?: string, password?: string, isSignUp?: boolean) => {
    const safePassword = password?.trim();
    const safeName = name?.trim() || email.split('@')[0];
    if (!email.trim() || !safePassword) {
      throw new Error('Enter your email and password to continue.');
    }

    const resp = isSignUp
      ? await registerApi(email.trim(), safePassword, safeName)
      : await loginApi(email.trim(), safePassword);
    const userObj: User = {
      id: resp.user.id,
      name: resp.user.name || safeName,
      email: resp.user.email || email.trim(),
      avatarUrl: DEFAULT_AVATAR,
      tier: resp.user.tier || 'free',
      plan: resp.user.plan || 'Free Plan',
    };

    localStorage.setItem('synccut_auth_token', resp.token);
    localStorage.setItem('synccut_auth_user', JSON.stringify(userObj));

    set({
      token: resp.token,
      user: userObj,
      isAuthenticated: true,
      isInitializing: false,
    });
  },

  logout: () => {
    void logoutApi().catch(() => undefined);
    localStorage.removeItem('synccut_auth_token');
    localStorage.removeItem('synccut_auth_user');
    set({
      token: null,
      user: null,
      isAuthenticated: false,
      isInitializing: false,
    });
  },
}));
