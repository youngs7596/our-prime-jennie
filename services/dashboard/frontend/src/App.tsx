import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import { useAuthStore } from '@/store/authStore'

// Lazy load pages for code splitting
const LoginPage = lazy(() => import('@/pages/Login').then(m => ({ default: m.LoginPage })))
const OverviewPage = lazy(() => import('@/pages/Overview').then(m => ({ default: m.OverviewPage })))
const PortfolioPage = lazy(() => import('@/pages/Portfolio').then(m => ({ default: m.PortfolioPage })))
const ScoutPage = lazy(() => import('@/pages/Scout').then(m => ({ default: m.ScoutPage })))
const SystemPage = lazy(() => import('@/pages/System').then(m => ({ default: m.SystemPage })))
const AnalyticsPage = lazy(() => import('@/pages/Analytics').then(m => ({ default: m.AnalyticsPage })))
const SettingsPage = lazy(() => import('@/pages/Settings').then(m => ({ default: m.SettingsPage })))

// Loading fallback component
function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const checkAuth = useAuthStore((state) => state.checkAuth)

  if (!isAuthenticated || !checkAuth()) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          {/* Public Routes */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected Routes */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<OverviewPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="scout" element={<ScoutPage />} />
            <Route path="system" element={<SystemPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
