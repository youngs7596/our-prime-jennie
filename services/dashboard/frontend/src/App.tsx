import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'

// Lazy load pages for code splitting
// 로그인 페이지 제거됨 - Cloudflare Access로 외부 인증 처리
const OverviewPage = lazy(() => import('@/pages/Overview').then(m => ({ default: m.OverviewPage })))
const PortfolioPage = lazy(() => import('@/pages/Portfolio').then(m => ({ default: m.PortfolioPage })))
const ScoutPage = lazy(() => import('@/pages/Scout').then(m => ({ default: m.ScoutPage })))
const SystemPage = lazy(() => import('@/pages/System').then(m => ({ default: m.SystemPage })))
const AnalyticsPage = lazy(() => import('@/pages/Analytics').then(m => ({ default: m.AnalyticsPage })))
const SettingsPage = lazy(() => import('@/pages/Settings').then(m => ({ default: m.SettingsPage })))
const MacroCouncilPage = lazy(() => import('@/pages/MacroCouncil').then(m => ({ default: m.MacroCouncilPage })))

// Loading fallback component
function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          {/* 모든 라우트 인증 없이 접근 가능 */}
          <Route path="/" element={<Layout />}>
            <Route index element={<OverviewPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="scout" element={<ScoutPage />} />
            <Route path="system" element={<SystemPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="macro-council" element={<MacroCouncilPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          {/* Fallback - /login 포함 모든 경로를 / 로 리다이렉트 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
