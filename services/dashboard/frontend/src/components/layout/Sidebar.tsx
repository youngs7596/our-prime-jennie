import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Briefcase,
  Brain,
  Activity,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  BarChart3,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useState } from 'react'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Home' },
  { path: '/portfolio', icon: Briefcase, label: 'Portfolio' },
  { path: '/scout', icon: Brain, label: 'Scout' },
  { path: '/system', icon: Activity, label: 'System' },
  { path: '/analytics', icon: BarChart3, label: 'Analytics' },
  { path: '/settings', icon: Settings, label: 'Settings' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const { logout, user } = useAuthStore()

  const isItemActive = (path: string) => location.pathname === path

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-screen z-40 flex flex-col',
        'border-r border-white/5 bg-black transition-all duration-200',
        collapsed ? 'w-16' : 'w-[240px]'
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between h-14 px-4 border-b border-white/5">
        <div
          className={cn(
            'flex items-center gap-3 overflow-hidden transition-all duration-200',
            collapsed && 'opacity-0 w-0'
          )}
        >
          <div className="w-8 h-8 rounded-lg bg-white flex items-center justify-center flex-shrink-0">
            <span className="text-black font-semibold text-sm">J</span>
          </div>
          <span className="font-semibold text-sm text-white whitespace-nowrap">
            Jennie
          </span>
        </div>
        {collapsed && (
          <div className="w-8 h-8 rounded-lg bg-white flex items-center justify-center">
            <span className="text-black font-semibold text-sm">J</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            'p-1.5 rounded-md transition-colors',
            'text-muted-foreground hover:text-white hover:bg-white/5',
            collapsed && 'mx-auto'
          )}
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto custom-scrollbar">
        {navItems.map((item) => {
          const active = isItemActive(item.path)

          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md transition-colors duration-150',
                'text-muted-foreground hover:text-white hover:bg-white/5',
                active && 'bg-white/10 text-white'
              )}
            >
              {/* Active indicator bar */}
              <div
                className={cn(
                  'absolute left-0 w-0.5 h-5 rounded-r-full bg-white transition-opacity',
                  active ? 'opacity-100' : 'opacity-0'
                )}
              />
              <item.icon className="w-[18px] h-[18px] flex-shrink-0" />
              <span
                className={cn(
                  'text-sm font-medium overflow-hidden whitespace-nowrap transition-all duration-200',
                  collapsed ? 'opacity-0 w-0' : 'opacity-100'
                )}
              >
                {item.label}
              </span>
            </NavLink>
          )
        })}
      </nav>

      {/* User & Logout */}
      <div className="p-3 border-t border-white/5">
        <div
          className={cn(
            'flex items-center gap-3 mb-2 px-2',
            collapsed && 'justify-center'
          )}
        >
          <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
            <span className="text-white text-sm font-medium">
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </span>
          </div>
          <div
            className={cn(
              'overflow-hidden transition-all duration-200',
              collapsed ? 'opacity-0 w-0' : 'opacity-100'
            )}
          >
            <p className="text-sm font-medium text-white truncate">
              {user?.username || 'User'}
            </p>
            <p className="text-xs text-muted-foreground">
              {user?.role || 'admin'}
            </p>
          </div>
        </div>
        <button
          onClick={logout}
          className={cn(
            'flex items-center gap-3 w-full px-3 py-2 rounded-md',
            'text-muted-foreground hover:text-red-400 hover:bg-red-500/10',
            'transition-colors duration-150',
            collapsed && 'justify-center'
          )}
        >
          <LogOut className="w-[18px] h-[18px] flex-shrink-0" />
          <span
            className={cn(
              'text-sm font-medium overflow-hidden whitespace-nowrap transition-all duration-200',
              collapsed ? 'opacity-0 w-0' : 'opacity-100'
            )}
          >
            Logout
          </span>
        </button>
      </div>
    </aside>
  )
}
