import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { api, analystApi } from '@/lib/api'
import { cn, formatCurrency, formatPercent, getProfitColor } from '@/lib/utils'
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  BarChart3,
  AlertTriangle,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'

type Tab = 'performance' | 'analyst'
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
    return_1d: number | null
    return_5d: number | null
    return_20d: number | null
  }>
  total_count?: number
}

export function AnalyticsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('performance')

  return (
    <div className="space-y-6">
      {/* Header with tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Analytics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            투자 성과 및 AI 분석가 퍼포먼스
          </p>
        </div>
        <div className="flex gap-1 p-1 bg-white/5 rounded-lg">
          <button
            onClick={() => setActiveTab('performance')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'performance'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            Performance
          </button>
          <button
            onClick={() => setActiveTab('analyst')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'analyst'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            AI Analyst
          </button>
        </div>
      </div>

      {activeTab === 'performance' ? <PerformanceTab /> : <AnalystTab />}
    </div>
  )
}

function PerformanceTab() {
  const [preset, setPreset] = useState<PeriodPreset>('month')
  const [data, setData] = useState<PerformanceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const presets: { value: PeriodPreset; label: string }[] = [
    { value: 'today', label: '오늘' },
    { value: 'week', label: '이번 주' },
    { value: 'month', label: '이번 달' },
    { value: 'year', label: '올해' },
    { value: 'all', label: '전체' },
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
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-muted-foreground">
        <AlertTriangle className="w-10 h-10 mb-4 text-yellow-500" />
        <p>{error}</p>
        <Button variant="outline" className="mt-4" onClick={fetchPerformance}>
          다시 시도
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Period selector */}
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

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <DollarSign className="w-4 h-4" />
              순수익 (실현)
            </div>
            <p
              className={cn(
                'text-2xl font-semibold',
                getProfitColor(data?.realized.net_profit || 0)
              )}
            >
              {formatCurrency(data?.realized.net_profit || 0)}
            </p>
            <div className="flex items-center gap-1 mt-1 text-sm">
              {(data?.realized.net_profit || 0) >= 0 ? (
                <TrendingUp className="w-4 h-4 text-green-500" />
              ) : (
                <TrendingDown className="w-4 h-4 text-red-500" />
              )}
              <span className={getProfitColor(data?.realized.net_profit_rate || 0)}>
                {formatPercent(data?.realized.net_profit_rate || 0)}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <Target className="w-4 h-4" />
              승률
            </div>
            <p className="text-2xl font-semibold text-white">
              {formatPercent(data?.stats.win_rate || 0)}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              {data?.stats.win_count || 0}승 / {data?.stats.loss_count || 0}패
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <BarChart3 className="w-4 h-4" />
              Profit Factor
            </div>
            <p className="text-2xl font-semibold text-white">
              {data?.stats.profit_factor ? data.stats.profit_factor.toFixed(2) : '∞'}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              {(data?.stats.profit_factor || 0) >= 1.5
                ? '양호'
                : (data?.stats.profit_factor || 0) >= 1
                ? '보통'
                : '주의'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <AlertTriangle className="w-4 h-4" />
              MDD
            </div>
            <p className={cn('text-2xl font-semibold', getProfitColor(data?.stats.mdd || 0))}>
              {formatPercent(data?.stats.mdd || 0)}
            </p>
            <p className="text-sm text-muted-foreground mt-1">기간 중 최대 손실폭</p>
          </CardContent>
        </Card>
      </div>

      {/* Unrealized P&L */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />
            현재 보유 자산 (평가손익)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">평가금액</p>
              <p className="text-lg font-medium text-white">
                {formatCurrency(data?.unrealized.total_value || 0)}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">매수원가</p>
              <p className="text-lg font-medium text-white">
                {formatCurrency(data?.unrealized.total_cost || 0)}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">평가손익</p>
              <p
                className={cn(
                  'text-lg font-medium',
                  getProfitColor(data?.unrealized.unrealized_profit || 0)
                )}
              >
                {formatCurrency(data?.unrealized.unrealized_profit || 0)}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">수익률</p>
              <p
                className={cn(
                  'text-lg font-medium',
                  getProfitColor(data?.unrealized.unrealized_profit_rate || 0)
                )}
              >
                {formatPercent(data?.unrealized.unrealized_profit_rate || 0)}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Cumulative profit chart */}
      {data?.cumulative_profit_curve && data.cumulative_profit_curve.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BarChart3 className="w-4 h-4" />
              누적 수익 추이
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.cumulative_profit_curve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="#666" />
                  <YAxis
                    tick={{ fontSize: 12 }}
                    tickFormatter={(v) => `${(v / 10000).toFixed(0)}만`}
                    stroke="#666"
                  />
                  <Tooltip
                    formatter={(value: number) => [formatCurrency(value), '누적 수익']}
                    contentStyle={{
                      backgroundColor: '#0a0a0a',
                      border: '1px solid #262626',
                      borderRadius: '6px',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="profit"
                    stroke="#0070F3"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* By stock breakdown */}
      {data?.by_stock && data.by_stock.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">종목별 실현 손익</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5 text-left text-muted-foreground">
                    <th className="pb-3 font-medium">종목</th>
                    <th className="pb-3 font-medium text-right">매수금액</th>
                    <th className="pb-3 font-medium text-right">매도금액</th>
                    <th className="pb-3 font-medium text-right">순수익</th>
                    <th className="pb-3 font-medium text-right">수익률</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_stock.map((stock) => (
                    <tr key={stock.stock_code} className="border-b border-white/5 last:border-0">
                      <td className="py-3">
                        <p className="font-medium text-white">{stock.stock_name}</p>
                        <p className="text-xs text-muted-foreground">{stock.stock_code}</p>
                      </td>
                      <td className="py-3 text-right font-mono">
                        {formatCurrency(stock.buy_amount)}
                      </td>
                      <td className="py-3 text-right font-mono">
                        {formatCurrency(stock.sell_amount)}
                      </td>
                      <td className={cn('py-3 text-right font-mono', getProfitColor(stock.net_profit))}>
                        {formatCurrency(stock.net_profit)}
                      </td>
                      <td className={cn('py-3 text-right font-mono', getProfitColor(stock.profit_rate))}>
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
    </div>
  )
}

function AnalystTab() {
  const [data, setData] = useState<AnalystData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(30)
  const [totalCount, setTotalCount] = useState(0)

  useEffect(() => {
    fetchData()
  }, [offset])

  const fetchData = async () => {
    try {
      setLoading(true)
      const res = await analystApi.getPerformance(limit, offset, 30)
      setData(res)
      setTotalCount(res.total_count || 0)
      setError(null)
    } catch (err: any) {
      setError('Failed to load analyst data')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !data?.overall) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-muted-foreground">
        <AlertTriangle className="w-10 h-10 mb-4" />
        <p>{error || 'No data available'}</p>
        <Button variant="outline" className="mt-4" onClick={fetchData}>
          Retry
        </Button>
      </div>
    )
  }

  const winRate = data.overall.win_rate_5d || 0
  const avgRet = data.overall.avg_return_5d || 0

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <Target className="w-4 h-4" />
              Win Rate (T+5)
            </div>
            <p className="text-2xl font-semibold text-white">{winRate.toFixed(1)}%</p>
            <p className="text-sm text-muted-foreground mt-1">
              {winRate >= 50 ? 'Target Met' : 'Below Target'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <TrendingUp className="w-4 h-4" />
              Avg Return (T+5)
            </div>
            <p className={cn('text-2xl font-semibold', avgRet >= 0 ? 'text-green-500' : 'text-red-500')}>
              {avgRet > 0 ? '+' : ''}
              {avgRet.toFixed(2)}%
            </p>
            <p className="text-sm text-muted-foreground mt-1">Per Decision</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <BarChart3 className="w-4 h-4" />
              Total Decisions
            </div>
            <p className="text-2xl font-semibold text-white">{data.overall.total_decisions}</p>
            <p className="text-sm text-muted-foreground mt-1">Analyzed Samples</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
              <Target className="w-4 h-4" />
              Market Regime
            </div>
            <p className="text-2xl font-semibold text-white">
              {data.by_regime.length > 0 ? 'Adaptive' : 'N/A'}
            </p>
            <p className="text-sm text-muted-foreground mt-1">Context Aware</p>
          </CardContent>
        </Card>
      </div>

      {/* Win Rate breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Target className="w-4 h-4" />
              Win Rate by Hunter Score
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.by_score.map((item) => (
              <div key={item.bucket} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">{item.bucket}</span>
                  <span
                    className={cn(
                      'font-medium',
                      item.win_rate >= 50 ? 'text-green-500' : 'text-red-500'
                    )}
                  >
                    {item.win_rate.toFixed(1)}% ({item.count})
                  </span>
                </div>
                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-all',
                      item.win_rate >= 50 ? 'bg-green-500' : 'bg-red-500'
                    )}
                    style={{ width: `${item.win_rate}%` }}
                  />
                </div>
              </div>
            ))}
            {data.by_score.length === 0 && (
              <p className="text-sm text-muted-foreground">Not enough data</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <BarChart3 className="w-4 h-4" />
              Win Rate by Market Regime
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.by_regime.map((item) => (
              <div key={item.regime} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">{item.regime}</span>
                  <span
                    className={cn(
                      'font-medium',
                      item.win_rate >= 50 ? 'text-green-500' : 'text-red-500'
                    )}
                  >
                    {item.win_rate.toFixed(1)}% ({item.count})
                  </span>
                </div>
                <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-all',
                      item.win_rate >= 50 ? 'bg-green-500' : 'bg-red-500'
                    )}
                    style={{ width: `${item.win_rate}%` }}
                  />
                </div>
              </div>
            ))}
            {data.by_regime.length === 0 && (
              <p className="text-sm text-muted-foreground">Not enough data</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent decisions table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Recent Decisions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/5 text-left text-muted-foreground">
                  <th className="pb-3 font-medium">Date</th>
                  <th className="pb-3 font-medium">Stock</th>
                  <th className="pb-3 font-medium">Decision</th>
                  <th className="pb-3 font-medium">Score</th>
                  <th className="pb-3 font-medium">Regime</th>
                  <th className="pb-3 font-medium text-right">T+1</th>
                  <th className="pb-3 font-medium text-right">T+5</th>
                  <th className="pb-3 font-medium text-right">T+20</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_decisions.map((row, i) => (
                  <tr key={i} className="border-b border-white/5 last:border-0">
                    <td className="py-3 text-muted-foreground">
                      {row.timestamp ? new Date(row.timestamp).toLocaleDateString() : '-'}
                    </td>
                    <td className="py-3">
                      <span className="text-white">{row.stock_name}</span>
                      <span className="text-xs text-muted-foreground ml-1">({row.stock_code})</span>
                    </td>
                    <td className="py-3">
                      <Badge variant={row.decision === 'BUY' ? 'success' : 'destructive'}>
                        {row.decision}
                      </Badge>
                    </td>
                    <td className="py-3 font-medium text-white">{row.hunter_score}</td>
                    <td className="py-3 text-muted-foreground">{row.market_regime || '-'}</td>
                    <td className="py-3 text-right">
                      {row.return_1d !== null ? (
                        <span className={row.return_1d >= 0 ? 'text-green-500' : 'text-red-500'}>
                          {row.return_1d > 0 ? '+' : ''}
                          {row.return_1d.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="py-3 text-right">
                      {row.return_5d !== null ? (
                        <span className={row.return_5d >= 0 ? 'text-green-500' : 'text-red-500'}>
                          {row.return_5d > 0 ? '+' : ''}
                          {row.return_5d.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="py-3 text-right">
                      {row.return_20d !== null ? (
                        <span className={row.return_20d >= 0 ? 'text-green-500' : 'text-red-500'}>
                          {row.return_20d > 0 ? '+' : ''}
                          {row.return_20d.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </td>
                  </tr>
                ))}
                {data.recent_decisions.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-muted-foreground">
                      No recent decisions found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/5">
            <span className="text-sm text-muted-foreground">
              {offset + 1} - {Math.min(offset + limit, totalCount)} of {totalCount}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
              >
                <ChevronLeft className="w-4 h-4" />
                Prev
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= totalCount}
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default AnalyticsPage
