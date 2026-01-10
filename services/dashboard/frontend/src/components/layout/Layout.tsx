import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

export function Layout() {
  return (
    <div className="min-h-screen bg-raydium-dark">
      {/* Raydium 스타일 - 네온 그라데이션 글로우 */}
      <div className="fixed inset-0 pointer-events-none">
        {/* 상단 퍼플 글로우 */}
        <div className="absolute top-0 left-1/4 w-[600px] h-[400px] bg-raydium-purple/20 rounded-full blur-[150px]" />
        {/* 우측 시안 글로우 */}
        <div className="absolute top-1/3 right-0 w-[400px] h-[400px] bg-raydium-cyan/10 rounded-full blur-[120px]" />
        {/* 그리드 패턴 */}
        <div className="absolute inset-0 bg-grid-pattern opacity-30" />
      </div>

      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <main className="ml-[280px] min-h-screen relative">
        <div className="p-8">
          <Outlet />
        </div>
      </main>

      {/* 노이즈 텍스처 오버레이 */}
      <div className="noise-overlay" />
    </div>
  )
}
