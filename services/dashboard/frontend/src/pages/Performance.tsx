import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatCurrency, formatPercent, getProfitColor } from '@/lib/utils'
import {
    TrendingUp,
    Calendar,
    DollarSign,
    Target,
    BarChart3,
    AlertTriangle,
    Loader2,
    ArrowUpRight,
    ArrowDownRight
} from 'lucide-react'
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer
} from 'recharts'

// 기간 프리셋 타입
type PeriodPreset = 'today' | 'week' | 'month' | 'year' | 'all'

interface PerformanceData {
    period: { start: string | null; end: string | null }
    realized: {
        total_buy_amount: number
        total_sell_amount: number
        gross_profit: number
        fees: number
        taxes: number
        net_profit: number
        net_profit_rate: number
    }
    unrealized: {
        total_value: number
        total_cost: number
        unrealized_profit: number
        unrealized_profit_rate: number
    }
    stats: {
        trade_count: { buy: number; sell: number }
        win_count: number
        loss_count: number
        win_rate: number
        profit_factor: number | null
        mdd: number
    }
    cumulative_profit_curve: { date: string; profit: number }[]
    by_stock: {
        stock_code: string
        stock_name: string
        buy_amount: number
        sell_amount: number
        net_profit: number
        profit_rate: number
    }[]
}

export function PerformancePage() {
    const [preset, setPreset] = useState<PeriodPreset>('month')
    const [data, setData] = useState<PerformanceData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const presets: { value: PeriodPreset; label: string }[] = [
        { value: 'today', label: '오늘' },
        { value: 'week', label: '이번 주' },
        { value: 'month', label: '이번 달' },
        { value: 'year', label: '올해' },
        { value: 'all', label: '전체' }
    ]

    useEffect(() => {
        fetchPerformance()
    }, [preset])

    const fetchPerformance = async () => {
        setLoading(true)
        setError(null)
        try {
            const response = await api.get(`/performance?preset=${preset}`)
            setData(response.data)
        } catch (err: any) {
            setError(err.message || '데이터 로딩 실패')
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-96">
                <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
            </div>
        )
    }

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center h-96 text-muted-foreground">
                <AlertTriangle className="w-12 h-12 mb-4 text-yellow-500" />
                <p>{error}</p>
                <Button variant="outline" className="mt-4" onClick={fetchPerformance}>
                    다시 시도
                </Button>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {/* 헤더 */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold">📊 투자 성과</h1>
                    <p className="text-muted-foreground">
                        Prime Jennie의 실현 및 평가 손익을 확인합니다
                    </p>
                </div>

                {/* 기간 프리셋 버튼 */}
                <div className="flex gap-2">
                    {presets.map((p) => (
                        <Button
                            key={p.value}
                            variant={preset === p.value ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => setPreset(p.value)}
                        >
                            {p.label}
                        </Button>
                    ))}
                </div>
            </div>

            {/* 핵심 지표 카드 */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* 순수익 */}
                <Card className="bg-gradient-to-br from-background to-muted/30">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                            <DollarSign className="w-4 h-4" />
                            순수익 (실현)
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className={cn(
                            'text-2xl font-bold',
                            getProfitColor(data?.realized.net_profit || 0)
                        )}>
                            {formatCurrency(data?.realized.net_profit || 0)}
                        </p>
                        <div className="flex items-center gap-1 mt-1">
                            {(data?.realized.net_profit || 0) >= 0 ? (
                                <ArrowUpRight className="w-4 h-4 text-profit-positive" />
                            ) : (
                                <ArrowDownRight className="w-4 h-4 text-profit-negative" />
                            )}
                            <span className={cn(
                                'text-sm font-medium',
                                getProfitColor(data?.realized.net_profit_rate || 0)
                            )}>
                                {formatPercent(data?.realized.net_profit_rate || 0)}
                            </span>
                        </div>
                    </CardContent>
                </Card>

                {/* 승률 */}
                <Card className="bg-gradient-to-br from-background to-muted/30">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                            <Target className="w-4 h-4" />
                            승률
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold">
                            {formatPercent(data?.stats.win_rate || 0)}
                        </p>
                        <p className="text-sm text-muted-foreground mt-1">
                            {data?.stats.win_count || 0}승 / {data?.stats.loss_count || 0}패
                        </p>
                    </CardContent>
                </Card>

                {/* Profit Factor */}
                <Card className="bg-gradient-to-br from-background to-muted/30">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                            <BarChart3 className="w-4 h-4" />
                            Profit Factor
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className="text-2xl font-bold">
                            {data?.stats.profit_factor
                                ? data.stats.profit_factor.toFixed(2)
                                : '∞'}
                        </p>
                        <p className="text-sm text-muted-foreground mt-1">
                            {(data?.stats.profit_factor || 0) >= 1.5
                                ? '🟢 양호'
                                : (data?.stats.profit_factor || 0) >= 1
                                    ? '🟡 보통'
                                    : '🔴 주의'}
                        </p>
                    </CardContent>
                </Card>

                {/* MDD */}
                <Card className="bg-gradient-to-br from-background to-muted/30">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                            <AlertTriangle className="w-4 h-4" />
                            최대 낙폭 (MDD)
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className={cn(
                            'text-2xl font-bold',
                            getProfitColor(data?.stats.mdd || 0)
                        )}>
                            {formatPercent(data?.stats.mdd || 0)}
                        </p>
                        <p className="text-sm text-muted-foreground mt-1">
                            기간 중 최대 손실폭
                        </p>
                    </CardContent>
                </Card>
            </div>

            {/* 평가 손익 (보조) */}
            <Card>
                <CardHeader>
                    <CardTitle className="text-lg flex items-center gap-2">
                        <TrendingUp className="w-5 h-5" />
                        현재 보유 자산 현황 (평가손익)
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div>
                            <p className="text-sm text-muted-foreground">평가금액</p>
                            <p className="text-xl font-semibold">
                                {formatCurrency(data?.unrealized.total_value || 0)}
                            </p>
                        </div>
                        <div>
                            <p className="text-sm text-muted-foreground">매수원가</p>
                            <p className="text-xl font-semibold">
                                {formatCurrency(data?.unrealized.total_cost || 0)}
                            </p>
                        </div>
                        <div>
                            <p className="text-sm text-muted-foreground">평가손익</p>
                            <p className={cn(
                                'text-xl font-semibold',
                                getProfitColor(data?.unrealized.unrealized_profit || 0)
                            )}>
                                {formatCurrency(data?.unrealized.unrealized_profit || 0)}
                            </p>
                        </div>
                        <div>
                            <p className="text-sm text-muted-foreground">수익률</p>
                            <p className={cn(
                                'text-xl font-semibold',
                                getProfitColor(data?.unrealized.unrealized_profit_rate || 0)
                            )}>
                                {formatPercent(data?.unrealized.unrealized_profit_rate || 0)}
                            </p>
                        </div>
                    </div>
                </CardContent>
            </Card>

            {/* 누적 수익 그래프 */}
            {data?.cumulative_profit_curve && data.cumulative_profit_curve.length > 0 && (
                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                            <BarChart3 className="w-5 h-5" />
                            누적 수익 추이
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="h-80">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={data.cumulative_profit_curve}>
                                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                    <XAxis
                                        dataKey="date"
                                        tick={{ fontSize: 12 }}
                                        className="text-muted-foreground"
                                    />
                                    <YAxis
                                        tick={{ fontSize: 12 }}
                                        tickFormatter={(v) => `${(v / 10000).toFixed(0)}만`}
                                        className="text-muted-foreground"
                                    />
                                    <Tooltip
                                        formatter={(value: number) => [formatCurrency(value), '누적 수익']}
                                        labelFormatter={(label) => `날짜: ${label}`}
                                        contentStyle={{
                                            backgroundColor: 'hsl(var(--card))',
                                            border: '1px solid hsl(var(--border))',
                                            borderRadius: '8px'
                                        }}
                                    />
                                    <Line
                                        type="monotone"
                                        dataKey="profit"
                                        stroke="hsl(var(--primary))"
                                        strokeWidth={2}
                                        dot={false}
                                    />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* 종목별 상세 */}
            {data?.by_stock && data.by_stock.length > 0 && (
                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                            <Calendar className="w-5 h-5" />
                            종목별 실현 손익
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="border-b text-left">
                                        <th className="pb-3 font-medium text-muted-foreground">종목</th>
                                        <th className="pb-3 font-medium text-muted-foreground text-right">매수금액</th>
                                        <th className="pb-3 font-medium text-muted-foreground text-right">매도금액</th>
                                        <th className="pb-3 font-medium text-muted-foreground text-right">순수익</th>
                                        <th className="pb-3 font-medium text-muted-foreground text-right">수익률</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.by_stock.map((stock) => (
                                        <tr key={stock.stock_code} className="border-b last:border-0">
                                            <td className="py-3">
                                                <div>
                                                    <p className="font-medium">{stock.stock_name}</p>
                                                    <p className="text-sm text-muted-foreground">{stock.stock_code}</p>
                                                </div>
                                            </td>
                                            <td className="py-3 text-right font-mono">
                                                {formatCurrency(stock.buy_amount)}
                                            </td>
                                            <td className="py-3 text-right font-mono">
                                                {formatCurrency(stock.sell_amount)}
                                            </td>
                                            <td className={cn(
                                                'py-3 text-right font-mono font-semibold',
                                                getProfitColor(stock.net_profit)
                                            )}>
                                                {formatCurrency(stock.net_profit)}
                                            </td>
                                            <td className={cn(
                                                'py-3 text-right font-mono',
                                                getProfitColor(stock.profit_rate)
                                            )}>
                                                {formatPercent(stock.profit_rate)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* 수수료/세금 상세 */}
            <Card className="bg-muted/30">
                <CardContent className="pt-6">
                    <div className="flex flex-wrap gap-6 text-sm text-muted-foreground">
                        <div>
                            <span className="font-medium">총 매수금액:</span>{' '}
                            {formatCurrency(data?.realized.total_buy_amount || 0)}
                        </div>
                        <div>
                            <span className="font-medium">총 매도금액:</span>{' '}
                            {formatCurrency(data?.realized.total_sell_amount || 0)}
                        </div>
                        <div>
                            <span className="font-medium">수수료:</span>{' '}
                            {formatCurrency(data?.realized.fees || 0)}
                        </div>
                        <div>
                            <span className="font-medium">거래세:</span>{' '}
                            {formatCurrency(data?.realized.taxes || 0)}
                        </div>
                        <div>
                            <span className="font-medium">거래 횟수:</span>{' '}
                            매수 {data?.stats.trade_count.buy || 0}건, 매도 {data?.stats.trade_count.sell || 0}건
                        </div>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}

export default PerformancePage
