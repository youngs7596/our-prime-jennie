import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

export function Layout() {
  return (
    <div className="min-h-screen bg-stripe-dark">
      {/* Stripe 스타일 - 미니멀 그라데이션 */}
      <div className="fixed inset-0 pointer-events-none bg-stripe-dark">
        <div className="absolute top-0 left-0 w-full h-[500px] bg-gradient-to-b from-stripe-indigo/10 to-transparent" />
      </div>

      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <main className="ml-[280px] min-h-screen relative">
        <div className="p-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

