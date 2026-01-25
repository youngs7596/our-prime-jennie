import { Outlet, NavLink, useLocation, Navigate } from 'react-router-dom';
import { motion } from 'framer-motion';

export default function LogicLayout() {
    const location = useLocation();
    const isRoot = location.pathname === '/visual-logic' || location.pathname === '/visual-logic/';

    // If visiting root /visual-logic, redirect to Junho (default) or show a landing
    // The user asked for "Visual Logic -> Quantum Logic -> [Person]". 
    // Let's implement a sub-navigation bar here.

    const tabs = [
        { path: 'junho', label: 'Junho\'s Logic' },
        { path: 'minji', label: 'Minji\'s Logic' },
        { path: 'jennie', label: 'Jennie\'s Logic' },
        { path: 'new', label: 'Dynamic (New)' },
    ];

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-display font-bold">Quantum Logic Visualization</h1>
                    <p className="text-muted-foreground mt-1">Visualize the Prime Jennie trading logic through different lenses.</p>
                </div>
            </div>

            {/* Sub Navigation */}
            <div className="flex gap-2 p-1 bg-black/20 rounded-lg w-fit">
                {tabs.map((tab) => (
                    <NavLink
                        key={tab.path}
                        to={tab.path}
                        className={({ isActive }) =>
                            `px-4 py-2 rounded-md transition-all ${isActive
                                ? 'bg-raydium-purple text-white shadow-neon-purple'
                                : 'text-muted-foreground hover:text-white hover:bg-white/5'
                            }`
                        }
                    >
                        {tab.label}
                    </NavLink>
                ))}
            </div>

            <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="min-h-[600px]"
            >
                {isRoot ? <Navigate to="junho" replace /> : <Outlet />}
            </motion.div>
        </div>
    );
}
