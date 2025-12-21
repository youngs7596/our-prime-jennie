
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { TrendingUp, BarChart2, CheckCircle, Target } from 'lucide-react'
import { analystApi } from '@/lib/api'

// Helper for conditional classes
const cn = (...classes: (string | undefined | null | false)[]) => classes.filter(Boolean).join(' ')

interface AnalystData {
    overall: {
        win_rate_5d: number | null
        avg_return_5d: number | null
        total_decisions: number
    } | null
    by_regime: Array<{
        regime: string
        count: number
        win_rate: number
        avg_return: number
    }>
    by_score: Array<{
        bucket: string
        count: number
        win_rate: number
        avg_return: number
    }>
    recent_decisions: Array<{
        timestamp: string
        stock_name: string
        stock_code: string
        decision: string
        hunter_score: number
        market_regime: string
        return_5d: number | null
    }>
}

export function AnalystPage() {
    const [data, setData] = useState<AnalystData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        fetchData()
    }, [])

    const fetchData = async () => {
        try {
            setLoading(true)
            const res = await analystApi.getPerformance()
            setData(res)
            setError(null)
        } catch (err: any) {
            console.error(err)
            setError('Failed to load analyst performance data.')
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return (
            <div className="p-8 text-center text-muted-foreground">
                <p>Analyzing AI Performance...</p>
            </div>
        )
    }

    if (error) {
        return (
            <div className="p-8 text-center text-profit-negative">
                <p>{error}</p>
                <button onClick={fetchData} className="mt-4 text-sm underline">Retry</button>
            </div>
        )
    }

    if (!data || !data.overall) {
        return (
            <div className="p-8 text-center text-muted-foreground">
                <p>No performance data available yet.</p>
            </div>
        )
    }

    // --- KPI Calculation (Visual Coloring)
    const winRate = data.overall.win_rate_5d || 0
    const avgRet = data.overall.avg_return_5d || 0
    // const isGood = winRate >= 55 && avgRet > 0

    return (
        <div className="p-8 space-y-8 animate-in fade-in duration-500">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-display font-bold text-white mb-2">AI Analyst Performance</h1>
                    <p className="text-muted-foreground">
                        Evaluating the "Realized Performance" of AI Buy/Sell decisions (T+5 Benchmark).
                    </p>
                </div>
                <button
                    onClick={fetchData}
                    className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm transition-colors"
                >
                    Refresh
                </button>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <KPICard
                    label="Win Rate (T+5)"
                    value={`${winRate.toFixed(1)}%`}
                    subValue={winRate >= 50 ? "Target Met" : "Below Target"}
                    icon={Target}
                    trend={winRate >= 55 ? 'up' : winRate < 45 ? 'down' : 'neutral'}
                />
                <KPICard
                    label="Avg Return (T+5)"
                    value={`${avgRet > 0 ? '+' : ''}${avgRet.toFixed(2)}%`}
                    subValue="Per Decision"
                    icon={TrendingUp}
                    trend={avgRet > 0 ? 'up' : 'down'}
                />
                <KPICard
                    label="Total Decisions"
                    value={data.overall.total_decisions.toString()}
                    subValue="Analyzed Samples"
                    icon={BarChart2}
                    trend="neutral"
                />
                <KPICard
                    label="Market Regime"
                    value={data.by_regime.length > 0 ? "Adaptive" : "N/A"}
                    subValue="Context Aware"
                    icon={CheckCircle}
                    trend="neutral"
                />
            </div>

            {/* Charts / Detailed Stats Section */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

                {/* Hunter Score Performance */}
                <div className="p-6 rounded-xl border border-white/10 bg-jennie-black/40">
                    <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                        <Target className="w-5 h-5 text-jennie-purple" />
                        Win Rate by Hunter Score
                    </h2>
                    <div className="space-y-4">
                        {data.by_score.map((item) => (
                            <div key={item.bucket} className="space-y-1">
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">{item.bucket}</span>
                                    <span className={`font-medium ${item.win_rate >= 50 ? 'text-profit-positive' : 'text-profit-negative'}`}>
                                        {item.win_rate.toFixed(1)}% ({item.count})
                                    </span>
                                </div>
                                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                                    <motion.div
                                        initial={{ width: 0 }}
                                        animate={{ width: `${item.win_rate}%` }}
                                        className={`h-full ${item.win_rate >= 50 ? 'bg-profit-positive' : 'bg-profit-negative'}`}
                                    />
                                </div>
                            </div>
                        ))}
                        {data.by_score.length === 0 && <p className="text-sm text-muted-foreground">Not enough data.</p>}
                    </div>
                </div>

                {/* Market Regime Performance */}
                <div className="p-6 rounded-xl border border-white/10 bg-jennie-black/40">
                    <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                        <BarChart2 className="w-5 h-5 text-jennie-blue" />
                        Win Rate by Market Regime
                    </h2>
                    <div className="space-y-4">
                        {data.by_regime.map((item) => (
                            <div key={item.regime} className="space-y-1">
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">{item.regime}</span>
                                    <span className={`font-medium ${item.win_rate >= 50 ? 'text-profit-positive' : 'text-profit-negative'}`}>
                                        {item.win_rate.toFixed(1)}% ({item.count})
                                    </span>
                                </div>
                                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                                    <motion.div
                                        initial={{ width: 0 }}
                                        animate={{ width: `${item.win_rate}%` }}
                                        className={`h-full ${item.win_rate >= 50 ? 'bg-profit-positive' : 'bg-profit-negative'}`}
                                    />
                                </div>
                            </div>
                        ))}
                        {data.by_regime.length === 0 && <p className="text-sm text-muted-foreground">Not enough data.</p>}
                    </div>
                </div>
            </div>

            {/* Recent Decisions Table */}
            <div className="rounded-xl border border-white/10 bg-jennie-black/40 overflow-hidden">
                <div className="p-6 border-b border-white/10">
                    <h2 className="text-lg font-bold">Recent Decisions Impact</h2>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                        <thead className="text-xs text-muted-foreground uppercase bg-white/5">
                            <tr>
                                <th className="px-6 py-3">Date</th>
                                <th className="px-6 py-3">Stock</th>
                                <th className="px-6 py-3">Decision</th>
                                <th className="px-6 py-3">Score</th>
                                <th className="px-6 py-3">Regime</th>
                                <th className="px-6 py-3 text-right">T+5 Return</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {data.recent_decisions.map((row, i) => (
                                <tr key={i} className="hover:bg-white/5 transition-colors">
                                    <td className="px-6 py-4 whitespace-nowrap text-muted-foreground">
                                        {row.timestamp ? new Date(row.timestamp).toLocaleDateString() : '-'}
                                    </td>
                                    <td className="px-6 py-4 font-medium text-white">
                                        {row.stock_name} <span className="text-xs text-muted-foreground">({row.stock_code})</span>
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className={cn(
                                            "px-2 py-1 rounded text-xs font-medium",
                                            row.decision === 'BUY' ? "bg-profit-positive/10 text-profit-positive" : "bg-profit-negative/10 text-profit-negative"
                                        )}>
                                            {row.decision}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className={cn(
                                            "font-medium",
                                            row.hunter_score >= 80 ? "text-jennie-purple" : row.hunter_score >= 60 ? "text-profit-positive" : "text-muted-foreground"
                                        )}>
                                            {row.hunter_score}
                                        </span>
                                    </td>
                                    <td className="px-6 py-4 text-muted-foreground">
                                        {row.market_regime || 'Unknown'}
                                    </td>
                                    <td className={cn(
                                        "px-6 py-4 text-right font-medium",
                                        (row.return_5d || 0) > 0 ? "text-profit-positive" : (row.return_5d || 0) < 0 ? "text-profit-negative" : "text-muted-foreground"
                                    )}>
                                        {row.return_5d !== null ? `${row.return_5d > 0 ? '+' : ''}${row.return_5d.toFixed(2)}%` : 'Pending'}
                                    </td>
                                </tr>
                            ))}
                            {data.recent_decisions.length === 0 && (
                                <tr>
                                    <td colSpan={6} className="px-6 py-8 text-center text-muted-foreground">No recent decisions found.</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

// KPI Card Component
function KPICard({ label, value, subValue, icon: Icon, trend }: { label: string, value: string, subValue: string, icon: any, trend: 'up' | 'down' | 'neutral' }) {
    const trendColor = trend === 'up' ? 'text-profit-positive' : trend === 'down' ? 'text-profit-negative' : 'text-muted-foreground'
    const bgTrend = trend === 'up' ? 'bg-profit-positive/10' : trend === 'down' ? 'bg-profit-negative/10' : 'bg-white/5'

    return (
        <div className="p-6 rounded-xl border border-white/10 bg-jennie-black/40 hover:bg-white/5 transition-colors">
            <div className="flex justify-between items-start mb-4">
                <div className={`p-2 rounded-lg ${bgTrend}`}>
                    <Icon className={`w-5 h-5 ${trendColor}`} />
                </div>
                {/* Optional mini sparkline could go here */}
            </div>
            <div>
                <p className="text-sm text-muted-foreground mb-1">{label}</p>
                <h3 className="text-2xl font-bold text-white mb-1">{value}</h3>
                <p className="text-xs text-muted-foreground">{subValue}</p>
            </div>
        </div>
    )
}
