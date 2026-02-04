import React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  PieChart,
  Activity,
  Brain,
  RefreshCw,
  Zap,
  Users,
  BarChart3,
  Globe,
  Shield,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart as RechartsPie,
  Pie,
  Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { portfolioApi, scoutApi, tradesApi, marketApi, councilApi, llmApi, macroApi } from '@/lib/api'
import {
  formatCurrency,
  formatPercent,
  formatNumber,
  formatRelativeTime,
  getProfitColor,
} from '@/lib/utils'
import { cn } from '@/lib/utils'

// Vercel/Stripe minimal color palette
const COLORS = ['#0070F3', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899']

interface StatCardProps {
  title: string
  value: string
  subValue?: string
  icon: React.ElementType
  trend?: number
  color?: string
}

function StatCard({ title, value, subValue, icon: Icon, trend, color }: StatCardProps) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">{title}</p>
            <p className="text-xl font-semibold">{value}</p>
            {subValue && (
              <p className={cn('text-xs font-medium', trend !== undefined && getProfitColor(trend))}>
                {subValue}
              </p>
            )}
          </div>
          <div
            className={cn(
              'p-2.5 rounded-lg',
              color || 'bg-white/5'
            )}
          >
            <Icon className="w-5 h-5 text-muted-foreground" />
          </div>
        </div>
        {trend !== undefined && (
          <div className="mt-3 flex items-center gap-1">
            {trend >= 0 ? (
              <TrendingUp className="w-3.5 h-3.5 text-profit-positive" />
            ) : (
              <TrendingDown className="w-3.5 h-3.5 text-profit-negative" />
            )}
            <span className={cn('text-xs', getProfitColor(trend))}>
              {formatPercent(trend)}
            </span>
            <span className="text-xs text-muted-foreground ml-1">vs 어제</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function OverviewPage() {
  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ['portfolio-summary'],
    queryFn: portfolioApi.getSummary,
    refetchInterval: 120000, // 2분 (1분 → 2분)
    staleTime: 60000,
  })

  const { data: positions } = useQuery({
    queryKey: ['portfolio-positions'],
    queryFn: portfolioApi.getPositions,
    refetchInterval: 120000, // 2분 (1분 → 2분)
    staleTime: 60000,
  })

  const { data: scoutStatus } = useQuery({
    queryKey: ['scout-status'],
    queryFn: scoutApi.getStatus,
    refetchInterval: 60000, // 1분 (30초 → 1분)
    staleTime: 30000,
  })

  const { data: recentTrades } = useQuery({
    queryKey: ['recent-trades'],
    queryFn: () => tradesApi.getRecent(5),
    staleTime: 60000,
  })

  const { data: marketRegime } = useQuery({
    queryKey: ['market-regime'],
    queryFn: marketApi.getRegime,
    refetchInterval: 300000, // 5분 유지
    staleTime: 180000,
  })

  const { data: councilReview } = useQuery({
    queryKey: ['council-review'],
    queryFn: councilApi.getDailyReview,
    refetchInterval: 600000, // 10분 유지
    staleTime: 300000,
  })

  const { data: macroInsight } = useQuery({
    queryKey: ['macro-insight'],
    queryFn: () => macroApi.getInsight(),
    refetchInterval: 300000, // 5분
    staleTime: 180000,
  })

  const { data: llmStats } = useQuery({
    queryKey: ['llm-stats'],
    queryFn: llmApi.getStats,
    refetchInterval: 300000, // 5분 (2분 → 5분)
    staleTime: 120000,
  })

  const { data: llmConfig } = useQuery({
    queryKey: ['llm-config'],
    queryFn: llmApi.getConfig,
    staleTime: 600000, // 설정은 자주 안 바뀜
  })

  // Portfolio pie chart data
  const pieData = positions?.slice(0, 10).map((p: any, i: number) => ({
    name: p.stock_name,
    value: p.weight,
    color: COLORS[i % COLORS.length],
  })) || []

  // Asset history data
  const { data: history } = useQuery({
    queryKey: ['portfolio-history'],
    queryFn: () => portfolioApi.getHistory(30),
    refetchInterval: 60000 * 60, // 1시간 유지
    staleTime: 60000 * 30, // 30분
  })

  const chartData = history?.map((item: any) => ({
    date: item.date.slice(5),
    value: item.total_asset,
  })) || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Overview</h1>
          <p className="text-sm text-muted-foreground mt-1">포트폴리오 현황을 한눈에 확인하세요</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetchSummary()}
          className="gap-2"
        >
          <RefreshCw className="w-4 h-4" />
          새로고침
        </Button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="총 자산"
          value={summaryLoading ? '...' : formatCurrency(summary?.total_value || 0)}
          subValue={summary ? formatPercent(summary.profit_rate) : undefined}
          icon={Wallet}
          trend={summary?.profit_rate}
        />
        <StatCard
          title="총 수익"
          value={summaryLoading ? '...' : formatCurrency(summary?.total_profit || 0)}
          icon={summary?.total_profit >= 0 ? TrendingUp : TrendingDown}
          color={summary?.total_profit >= 0 ? 'bg-profit-positive/10' : 'bg-profit-negative/10'}
        />
        <StatCard
          title="보유 종목"
          value={summaryLoading ? '...' : `${summary?.positions_count || 0}개`}
          subValue={`현금: ${formatCurrency(summary?.cash_balance || 0)}`}
          icon={PieChart}
        />
        <StatCard
          title="Scout Pipeline"
          value={scoutStatus?.final_selected > 0 ? `${scoutStatus.final_selected}개 선정` : scoutStatus?.status === 'running' ? '실행 중' : '대기'}
          subValue={scoutStatus?.final_selected > 0 ? 'Watchlist 저장 완료' : scoutStatus?.phase_name || 'Phase 1 대기'}
          icon={Brain}
          color="bg-blue-500/10"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Asset Chart */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Activity className="w-4 h-4 text-muted-foreground" />
                자산 추이
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-[300px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#0070F3" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#0070F3" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                    <XAxis
                      dataKey="date"
                      stroke="#A3A3A3"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      stroke="#A3A3A3"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      tickFormatter={(v) => formatCurrency(v)}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#0A0A0A',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number) => [formatCurrency(value), '자산']}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="#0070F3"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorValue)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Portfolio Pie Chart */}
        <div>
          <Card className="h-full">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <PieChart className="w-4 h-4 text-muted-foreground" />
                포트폴리오 구성
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-[180px]">
                <ResponsiveContainer width="100%" height="100%">
                  <RechartsPie>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={70}
                      paddingAngle={2}
                      dataKey="value"
                    >
                      {pieData.map((entry: any, index: number) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#0A0A0A',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '6px',
                        fontSize: '12px',
                      }}
                      formatter={(value: number) => [`${value.toFixed(1)}%`, '비중']}
                    />
                  </RechartsPie>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 space-y-1.5">
                {pieData.slice(0, 5).map((item: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: item.color }}
                      />
                      <span className="text-muted-foreground truncate max-w-[100px]">{item.name}</span>
                    </div>
                    <span className="font-medium">{item.value.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Recent Trades */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">최근 거래</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {recentTrades?.length === 0 && (
              <p className="text-center text-muted-foreground py-8 text-sm">
                최근 거래 내역이 없습니다
              </p>
            )}
            {recentTrades?.map((trade: any) => (
              <div
                key={trade.id}
                className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] border border-white/5 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      'px-2 py-0.5 rounded text-xs font-medium',
                      trade.trade_type === 'BUY'
                        ? 'bg-profit-positive/10 text-profit-positive'
                        : 'bg-profit-negative/10 text-profit-negative'
                    )}
                  >
                    {trade.trade_type === 'BUY' ? '매수' : '매도'}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{trade.stock_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {trade.stock_code}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm font-mono">
                    {formatNumber(trade.quantity)}주 × {formatNumber(trade.price)}원
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatRelativeTime(trade.traded_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Scout Pipeline Status */}
      {scoutStatus && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Brain className="w-4 h-4 text-muted-foreground" />
              Scout-Debate-Judge Pipeline
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              {['Hunter Scout', 'Bull vs Bear Debate', 'Final Judge'].map((phase, i) => (
                <div
                  key={phase}
                  className={cn(
                    'p-3 rounded-lg border transition-colors',
                    scoutStatus.phase === i + 1
                      ? 'border-blue-500/50 bg-blue-500/10'
                      : scoutStatus.phase > i + 1
                        ? 'border-green-500/30 bg-green-500/5'
                        : 'border-white/5 bg-white/[0.02]'
                  )}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className={cn(
                        'w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium',
                        scoutStatus.phase === i + 1
                          ? 'bg-blue-500 text-white'
                          : scoutStatus.phase > i + 1
                            ? 'bg-green-500 text-white'
                            : 'bg-white/10 text-muted-foreground'
                      )}
                    >
                      {i + 1}
                    </div>
                    <span className="text-xs font-medium">{phase}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {i === 0 && `통과: ${scoutStatus.passed_phase1 || 0}개`}
                    {i === 1 && `토론: ${scoutStatus.passed_phase2 || 0}개`}
                    {i === 2 && `선정: ${scoutStatus.final_selected || 0}개`}
                  </p>
                </div>
              ))}
            </div>
            {scoutStatus.current_stock && (
              <p className="mt-3 text-xs text-muted-foreground">
                현재 분석 중: <span className="text-foreground">{scoutStatus.current_stock}</span>
              </p>
            )}
            {llmStats?.decisions_today && (
              <div className="mt-3 pt-3 border-t border-white/5 flex items-center gap-4 text-xs">
                <span className="text-muted-foreground">오늘 Scout 판정:</span>
                <span className="text-profit-positive">✓ BUY {llmStats.decisions_today.buy}건</span>
                <span className="text-profit-negative">✗ REJECT {llmStats.decisions_today.reject}건</span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Market Regime */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <BarChart3 className="w-4 h-4 text-muted-foreground" />
            시장 국면 (Market Regime)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-6">
            <div className={cn(
              'px-5 py-2.5 rounded-lg text-lg font-semibold',
              marketRegime?.regime === 'BULL' && 'bg-profit-positive/10 text-profit-positive',
              marketRegime?.regime === 'BEAR' && 'bg-profit-negative/10 text-profit-negative',
              marketRegime?.regime === 'SIDEWAYS' && 'bg-yellow-500/10 text-yellow-400',
              (!marketRegime?.regime || marketRegime?.regime === 'UNKNOWN' || marketRegime?.regime === 'ERROR') && 'bg-white/5 text-muted-foreground'
            )}>
              {marketRegime?.regime === 'BULL' && '🐂 상승장'}
              {marketRegime?.regime === 'BEAR' && '🐻 하락장'}
              {marketRegime?.regime === 'SIDEWAYS' && '↔️ 박스권'}
              {(!marketRegime?.regime || marketRegime?.regime === 'UNKNOWN' || marketRegime?.regime === 'ERROR') && '🚧 미구현'}
            </div>
            {marketRegime?.confidence ? (
              <div className="text-xs text-muted-foreground">
                신뢰도: <span className="text-foreground font-medium">{(marketRegime.confidence * 100).toFixed(0)}%</span>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">
                향후 구현 예정
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Macro Insight - Council 분석 결과 */}
      {macroInsight && macroInsight.insight_date && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Globe className="w-4 h-4 text-muted-foreground" />
              매크로 인사이트 (Council 분석)
              <span className="text-xs text-muted-foreground ml-2">{macroInsight.insight_date}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* 글로벌 데이터 */}
              <div className="space-y-3">
                <p className="text-xs font-medium text-muted-foreground">글로벌 지표</p>
                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    <p className="text-xs text-muted-foreground">VIX</p>
                    <p className={cn(
                      'text-lg font-semibold',
                      macroInsight.vix_regime === 'crisis' && 'text-red-400',
                      macroInsight.vix_regime === 'elevated' && 'text-yellow-400',
                      macroInsight.vix_regime === 'normal' && 'text-blue-400',
                      macroInsight.vix_regime === 'low_vol' && 'text-green-400',
                    )}>
                      {Number(macroInsight.vix_value || 0).toFixed(1)}
                    </p>
                    <p className="text-xs text-muted-foreground">{macroInsight.vix_regime || '-'}</p>
                  </div>
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    <p className="text-xs text-muted-foreground">USD/KRW</p>
                    <p className="text-lg font-semibold">{Number(macroInsight.usd_krw || 0).toFixed(1)}</p>
                  </div>
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    <p className="text-xs text-muted-foreground">KOSPI</p>
                    <p className="text-lg font-semibold">{Number(macroInsight.kospi_index || 0).toFixed(0)}</p>
                  </div>
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    <p className="text-xs text-muted-foreground">KOSDAQ</p>
                    <p className="text-lg font-semibold">{Number(macroInsight.kosdaq_index || 0).toFixed(0)}</p>
                  </div>
                </div>
                {/* 수급 데이터 */}
                {(macroInsight.kospi_foreign_net !== null || macroInsight.kospi_institutional_net !== null) && (
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    <p className="text-xs text-muted-foreground mb-2">투자자별 순매수 (억원)</p>
                    <div className="space-y-1 text-xs">
                      <div className="flex justify-between">
                        <span>외국인</span>
                        <span className={macroInsight.kospi_foreign_net >= 0 ? 'text-profit-positive' : 'text-profit-negative'}>
                          {macroInsight.kospi_foreign_net >= 0 ? '+' : ''}{(macroInsight.kospi_foreign_net || 0).toLocaleString()}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>기관</span>
                        <span className={macroInsight.kospi_institutional_net >= 0 ? 'text-profit-positive' : 'text-profit-negative'}>
                          {macroInsight.kospi_institutional_net >= 0 ? '+' : ''}{(macroInsight.kospi_institutional_net || 0).toLocaleString()}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>개인</span>
                        <span className={macroInsight.kospi_retail_net >= 0 ? 'text-profit-positive' : 'text-profit-negative'}>
                          {macroInsight.kospi_retail_net >= 0 ? '+' : ''}{(macroInsight.kospi_retail_net || 0).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Trading Recommendations */}
              <div className="space-y-3">
                <p className="text-xs font-medium text-muted-foreground">트레이딩 권고</p>
                <div className="grid grid-cols-2 gap-2">
                  <div className="p-2 rounded bg-blue-500/5 border border-blue-500/20">
                    <p className="text-xs text-muted-foreground">포지션 크기</p>
                    <p className="text-xl font-semibold text-blue-400">{macroInsight.position_size_pct || 100}%</p>
                  </div>
                  <div className="p-2 rounded bg-orange-500/5 border border-orange-500/20">
                    <p className="text-xs text-muted-foreground">손절폭 조정</p>
                    <p className="text-xl font-semibold text-orange-400">{macroInsight.stop_loss_adjust_pct || 100}%</p>
                  </div>
                </div>
                {/* 유리한 전략 */}
                {macroInsight.strategies_to_favor?.length > 0 && (
                  <div className="p-2 rounded bg-green-500/5 border border-green-500/20">
                    <p className="text-xs text-muted-foreground mb-1">허용 전략</p>
                    <div className="flex flex-wrap gap-1">
                      {macroInsight.strategies_to_favor.map((s: string, i: number) => (
                        <span key={i} className="px-1.5 py-0.5 text-xs bg-green-500/20 text-green-400 rounded">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {/* 피해야 할 전략 */}
                {macroInsight.strategies_to_avoid?.length > 0 && (
                  <div className="p-2 rounded bg-red-500/5 border border-red-500/20">
                    <p className="text-xs text-muted-foreground mb-1">회피 전략</p>
                    <div className="flex flex-wrap gap-1">
                      {macroInsight.strategies_to_avoid.map((s: string, i: number) => (
                        <span key={i} className="px-1.5 py-0.5 text-xs bg-red-500/20 text-red-400 rounded">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Sentiment & Risk */}
              <div className="space-y-3">
                <p className="text-xs font-medium text-muted-foreground">센티먼트 & 리스크</p>
                {/* Sentiment */}
                <div className={cn(
                  'p-3 rounded border',
                  macroInsight.sentiment?.includes('bullish') && 'bg-green-500/5 border-green-500/20',
                  macroInsight.sentiment?.includes('bearish') && 'bg-red-500/5 border-red-500/20',
                  macroInsight.sentiment?.includes('neutral') && 'bg-yellow-500/5 border-yellow-500/20',
                )}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">Council Sentiment</span>
                    <span className="text-lg font-semibold">{macroInsight.sentiment_score || '-'}</span>
                  </div>
                  <p className={cn(
                    'text-sm font-medium mt-1',
                    macroInsight.sentiment?.includes('bullish') && 'text-green-400',
                    macroInsight.sentiment?.includes('bearish') && 'text-red-400',
                    macroInsight.sentiment?.includes('neutral') && 'text-yellow-400',
                  )}>
                    {macroInsight.sentiment || '-'}
                  </p>
                </div>
                {/* Political Risk */}
                <div className={cn(
                  'p-3 rounded border',
                  macroInsight.political_risk_level === 'critical' && 'bg-red-500/10 border-red-500/30',
                  macroInsight.political_risk_level === 'high' && 'bg-orange-500/10 border-orange-500/30',
                  macroInsight.political_risk_level === 'medium' && 'bg-yellow-500/10 border-yellow-500/30',
                  macroInsight.political_risk_level === 'low' && 'bg-green-500/10 border-green-500/30',
                )}>
                  <div className="flex items-center gap-2 mb-1">
                    <Shield className="w-4 h-4" />
                    <span className="text-xs text-muted-foreground">Political Risk</span>
                    <span className={cn(
                      'px-1.5 py-0.5 text-xs rounded font-medium ml-auto',
                      macroInsight.political_risk_level === 'critical' && 'bg-red-500 text-white',
                      macroInsight.political_risk_level === 'high' && 'bg-orange-500 text-white',
                      macroInsight.political_risk_level === 'medium' && 'bg-yellow-500 text-black',
                      macroInsight.political_risk_level === 'low' && 'bg-green-500 text-white',
                    )}>
                      {macroInsight.political_risk_level?.toUpperCase() || 'UNKNOWN'}
                    </span>
                  </div>
                  {macroInsight.political_risk_summary && (
                    <p className="text-xs text-muted-foreground line-clamp-3">{macroInsight.political_risk_summary}</p>
                  )}
                </div>
                {/* 섹터 */}
                {(macroInsight.sectors_to_favor?.length > 0 || macroInsight.sectors_to_avoid?.length > 0) && (
                  <div className="p-2 rounded bg-white/[0.02] border border-white/5">
                    {macroInsight.sectors_to_favor?.length > 0 && (
                      <div className="mb-2">
                        <p className="text-xs text-muted-foreground mb-1">유망 섹터</p>
                        <div className="flex flex-wrap gap-1">
                          {macroInsight.sectors_to_favor.slice(0, 4).map((s: string, i: number) => (
                            <span key={i} className="px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded">{s}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {macroInsight.sectors_to_avoid?.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">회피 섹터</p>
                        <div className="flex flex-wrap gap-1">
                          {macroInsight.sectors_to_avoid.slice(0, 4).map((s: string, i: number) => (
                            <span key={i} className="px-1.5 py-0.5 text-xs bg-gray-500/20 text-gray-400 rounded">{s}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            {/* Trading Reasoning */}
            {macroInsight.trading_reasoning && (
              <div className="mt-4 p-3 rounded bg-white/[0.02] border border-white/5">
                <p className="text-xs text-muted-foreground mb-1">Council 판단 근거</p>
                <p className="text-xs text-foreground">{macroInsight.trading_reasoning}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* LLM Stats */}
      {llmStats && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Zap className="w-4 h-4 text-muted-foreground" />
              LLM 사용 통계 & 모델 정보
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-green-500/5 border border-green-500/20">
                <p className="text-xs text-muted-foreground mb-1">News Analysis (Fast)</p>
                <p className="text-xs font-medium text-green-400 truncate">
                  {llmConfig?.fast ? `${llmConfig.fast.provider.toUpperCase()} ${llmConfig.fast.model_name}` : 'Loading...'}
                </p>
                <div className="mt-2 text-right">
                  <p className="text-lg font-semibold text-green-400">{llmStats.news_analysis?.calls || llmStats.fast?.calls || 0}회</p>
                  <p className="text-xs text-green-400/60">
                    {((llmStats.news_analysis?.tokens || 0)).toLocaleString()} tokens
                  </p>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                <p className="text-xs text-muted-foreground mb-1">Scout & Debate (Reasoning)</p>
                <p className="text-xs font-medium text-blue-400 truncate">
                  {llmConfig?.reasoning ? `${llmConfig.reasoning.provider.toUpperCase()} ${llmConfig.reasoning.model_name}` : 'Loading...'}
                </p>
                <div className="mt-2 text-right">
                  <p className="text-lg font-semibold text-blue-400">{llmStats.scout?.calls || llmStats.reasoning?.calls || 0}회</p>
                  <p className="text-xs text-blue-400/60">
                    {((llmStats.scout?.tokens || 0)).toLocaleString()} tokens
                  </p>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-purple-500/5 border border-purple-500/20">
                <p className="text-xs text-muted-foreground mb-1">Judge & Briefing (Thinking)</p>
                <p className="text-xs font-medium text-purple-400 truncate">
                  {llmConfig?.thinking ? `${llmConfig.thinking.provider.toUpperCase()} ${llmConfig.thinking.model_name}` : 'Loading...'}
                </p>
                <div className="mt-2 text-right">
                  <p className="text-lg font-semibold text-purple-400">{llmStats.briefing?.calls || llmStats.thinking?.calls || 0}회</p>
                  <p className="text-xs text-purple-400/60">
                    {((llmStats.briefing?.tokens || 0)).toLocaleString()} tokens
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 3 Sages Council Review */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Users className="w-4 h-4 text-muted-foreground" />
            3현자 데일리 리뷰 (Daily Council)
            {councilReview?.date && (
              <span className="text-xs text-muted-foreground ml-2">{councilReview.date}</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {councilReview?.sages?.length > 0 ? (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {councilReview.sages.map((sage: any) => (
                  <div key={sage.name} className="p-3 rounded-lg bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xl">{sage.icon}</span>
                      <div>
                        <p className="text-sm font-medium">{sage.name}</p>
                        <p className="text-xs text-muted-foreground">{sage.role}</p>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground line-clamp-4">{sage.review}</p>
                  </div>
                ))}
              </div>
              {councilReview.consensus && (
                <div className="mt-3 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                  <p className="text-xs font-medium text-blue-400">📋 합의 사항</p>
                  <p className="text-xs text-muted-foreground mt-1">{councilReview.consensus}</p>
                </div>
              )}
            </>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">👑</span>
                  <div>
                    <p className="text-sm font-medium">Jennie</p>
                    <p className="text-xs text-muted-foreground">수석 심판 (Chief Judge)</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">오늘의 리뷰가 아직 생성되지 않았습니다.</p>
              </div>
              <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">🔍</span>
                  <div>
                    <p className="text-sm font-medium">Minji</p>
                    <p className="text-xs text-muted-foreground">리스크 분석가 (Risk Analyst)</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">시스템 분석을 기다리고 있습니다.</p>
              </div>
              <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">📈</span>
                  <div>
                    <p className="text-sm font-medium">Junho</p>
                    <p className="text-xs text-muted-foreground">전략가 (Strategist)</p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">전략 검토를 준비 중입니다.</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default OverviewPage
