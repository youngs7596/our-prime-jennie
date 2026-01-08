import { NavLink, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Briefcase,
  Brain,
  Activity,
  Newspaper,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Target,
  LineChart,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useState } from 'react'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Overview' },
  { path: '/portfolio', icon: Briefcase, label: 'Portfolio' },
  { path: '/scout', icon: Brain, label: 'Scout Pipeline' },
  { path: '/system', icon: Activity, label: 'System Status' },
  { path: '/news', icon: Newspaper, label: 'News & Sentiment' },
  { path: '/analyst', icon: Target, label: 'AI Analyst' },
  { path: '/logic', icon: Brain, label: 'Trading Logic' },
  { path: '/visual-logic', icon: LineChart, label: 'Visual Logic' },
  { path: '/settings', icon: Settings, label: 'Settings' },
]


export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const { logout, user } = useAuthStore()

  return (
    <motion.aside
      initial={{ width: 280 }}
      animate={{ width: collapsed ? 80 : 280 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className="fixed left-0 top-0 h-screen z-40 flex flex-col border-r border-raydium-purple/20 bg-raydium-darker/90 backdrop-blur-xl"
    >
      {/* Logo - Raydium Neon Style */}
      <div className="flex items-center justify-between h-16 px-4 border-b border-raydium-purple/20">
        <motion.div
          initial={{ opacity: 1 }}
          animate={{ opacity: collapsed ? 0 : 1 }}
          className="flex items-center gap-3"
        >
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-raydium-purple to-raydium-blue flex items-center justify-center shadow-neon-purple">
            <span className="text-white font-bold text-lg">J</span>
          </div>
          <div className="overflow-hidden">
            <h1 className="font-display font-bold text-lg gradient-text">
              Jennie
            </h1>
            <p className="text-xs text-raydium-cyan/70">AI Trading</p>
          </div>
        </motion.div>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-2 rounded-lg hover:bg-raydium-purple/20 transition-colors text-muted-foreground hover:text-raydium-purpleLight"
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <ChevronLeft className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Navigation - Raydium Neon Style */}
      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto custom-scrollbar">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300',
                'hover:bg-raydium-purple/10',
                isActive && 'bg-raydium-purple/20 border border-raydium-purple/40 shadow-neon-purple'
              )}
            >
              <item.icon
                className={cn(
                  'w-5 h-5 flex-shrink-0 transition-colors duration-300',
                  isActive ? 'text-raydium-purpleLight' : 'text-muted-foreground'
                )}
              />
              <motion.span
                initial={{ opacity: 1 }}
                animate={{ opacity: collapsed ? 0 : 1, width: collapsed ? 0 : 'auto' }}
                className={cn(
                  'text-sm font-medium overflow-hidden whitespace-nowrap transition-colors duration-300',
                  isActive ? 'text-white' : 'text-muted-foreground'
                )}
              >
                {item.label}
              </motion.span>
            </NavLink>
          )
        })}
      </nav>

      {/* User & Logout - Raydium Style */}
      <div className="p-4 border-t border-raydium-purple/20">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-raydium-purple to-raydium-cyan flex items-center justify-center shadow-neon-purple">
            <span className="text-white font-medium">
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </span>
          </div>
          <motion.div
            initial={{ opacity: 1 }}
            animate={{ opacity: collapsed ? 0 : 1 }}
            className="overflow-hidden"
          >
            <p className="text-sm font-medium text-white">{user?.username || 'User'}</p>
            <p className="text-xs text-raydium-cyan/70">{user?.role || 'admin'}</p>
          </motion.div>
        </div>
        <button
          onClick={logout}
          className={cn(
            'flex items-center gap-3 w-full px-3 py-2 rounded-xl',
            'text-muted-foreground hover:text-red-400 hover:bg-red-500/10',
            'transition-all duration-300 hover:shadow-neon-pink'
          )}
        >
          <LogOut className="w-5 h-5 flex-shrink-0" />
          <motion.span
            initial={{ opacity: 1 }}
            animate={{ opacity: collapsed ? 0 : 1 }}
            className="text-sm font-medium"
          >
            Logout
          </motion.span>
        </button>
      </div>
    </motion.aside>
  )
}
