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
  Map,
  Zap,
  Server,
  Sparkles,
  Star,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useState } from 'react'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Overview' },
  { path: '/portfolio', icon: Briefcase, label: 'Portfolio' },
  { path: '/performance', icon: LineChart, label: '투자 성과' },
  { path: '/scout', icon: Brain, label: 'Scout Pipeline' },
  { path: '/system', icon: Activity, label: 'System Status' },
  { path: '/news', icon: Newspaper, label: 'News & Sentiment' },
  { path: '/analyst', icon: Target, label: 'AI Analyst' },
  { path: '/logic', icon: Brain, label: 'Trading Logic' },
  {
    path: '/visual-logic',
    icon: LineChart,
    label: 'Visual Logic',
    children: [
      { path: '/visual-logic/junho', label: 'Junho (준호)', icon: Zap },
      { path: '/visual-logic/minji', label: 'Minji (민지)', icon: Sparkles },
      { path: '/visual-logic/jennie', label: 'Jennie (제니)', icon: Star },
      { path: '/visual-logic/new', label: 'Dynamic (New)', icon: Target },
    ]
  },
  { path: '/trading', icon: Zap, label: 'Trading' },

  { path: '/architecture', icon: Map, label: 'Architecture' },
  { path: '/super-prime', icon: Target, label: 'Super Prime' },
  { path: '/settings', icon: Settings, label: 'Settings' },
  { path: '/arrow-buttons', icon: LineChart, label: 'Dev: UI' },
  { path: '/operations', icon: Server, label: 'Operations' },
]


export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const { logout, user } = useAuthStore()

  // Helper to check if a path is active (including children)
  const isItemActive = (item: any) => {
    if (location.pathname === item.path) return true;
    if (item.children) {
      return item.children.some((child: any) => location.pathname === child.path);
    }
    return false;
  };

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
          // Check if parent or any child is active
          const active = isItemActive(item);
          // Check if parent specifically is active (if it has a path)


          return (
            <div key={item.path}>
              <NavLink
                to={item.path}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300',
                  'hover:bg-raydium-purple/10',
                  active && !item.children && 'bg-raydium-purple/20 border border-raydium-purple/40 shadow-neon-purple'
                )}
              >
                <item.icon
                  className={cn(
                    'w-5 h-5 flex-shrink-0 transition-colors duration-300',
                    active ? 'text-raydium-purpleLight' : 'text-muted-foreground'
                  )}
                />
                <motion.span
                  initial={{ opacity: 1 }}
                  animate={{ opacity: collapsed ? 0 : 1, width: collapsed ? 0 : 'auto' }}
                  className={cn(
                    'text-sm font-medium overflow-hidden whitespace-nowrap transition-colors duration-300',
                    active ? 'text-white' : 'text-muted-foreground'
                  )}
                >
                  {item.label}
                </motion.span>
              </NavLink>

              {/* Render Children if any and not collapsed */}
              {item.children && !collapsed && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="ml-9 mt-1 space-y-1 border-l border-white/10 pl-2"
                >
                  {item.children.map((child) => {
                    const childActive = location.pathname === child.path;

                    return (
                      <NavLink
                        key={child.path}
                        to={child.path}
                        className={cn(
                          'flex items-center gap-2 px-3 py-2 rounded-lg transition-all',
                          'hover:text-white hover:bg-white/5',
                          childActive ? 'text-raydium-purpleLight bg-raydium-purple/10' : 'text-muted-foreground'
                        )}
                      >
                        {child.icon && <child.icon className="w-4 h-4" />}
                        <span className="text-sm">{child.label}</span>
                      </NavLink>
                    )
                  })}
                </motion.div>
              )}
            </div>
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
