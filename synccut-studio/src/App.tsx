import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { Toaster } from 'sonner';

import Landing from '@/pages/Landing';
import Login from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import Workspace from '@/pages/Workspace';
import { ProtectedRoute } from '@/components/ProtectedRoute';
import { useAuthStore } from '@/store/useAuthStore';

// Framer Motion Page Transition Wrapper
const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className="min-h-screen w-full"
    >
      {children}
    </motion.div>
  );
};

// Animated Route Switcher
const AnimatedRoutes: React.FC = () => {
  const location = useLocation();

  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        {/* Public Landing Page */}
        <Route
          path="/"
          element={
            <PageTransition>
              <Landing />
            </PageTransition>
          }
        />

        {/* Auth / Login Page */}
        <Route
          path="/login"
          element={
            <PageTransition>
              <Login />
            </PageTransition>
          }
        />

        {/* User Dashboard (Protected) */}
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <PageTransition>
                <Dashboard />
              </PageTransition>
            </ProtectedRoute>
          }
        />

        {/* Workspace Direct Access (Redirects to a new project if no ID provided) */}
        <Route
          path="/workspace"
          element={
            <ProtectedRoute>
              <PageTransition>
                <Workspace />
              </PageTransition>
            </ProtectedRoute>
          }
        />

        {/* Workspace by Project ID (Protected) - THIS IS THE NLE */}
        <Route
          path="/workspace/:projectId"
          element={
            <ProtectedRoute>
              <PageTransition>
                <Workspace />
              </PageTransition>
            </ProtectedRoute>
          }
        />

        {/* Catch-all fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  );
};

export default function App() {
  const { initialize } = useAuthStore();

  useEffect(() => {
    initialize();
  }, [initialize]);

  return (
    <BrowserRouter>
      {/* Toast Notification Provider (Sonner) styled for dark cyan aesthetic */}
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: '#141418',
            border: '1px solid #2a2a32',
            color: '#ededed',
            fontSize: '13px',
          },
        }}
      />
      <AnimatedRoutes />
    </BrowserRouter>
  );
}