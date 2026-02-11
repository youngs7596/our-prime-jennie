import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Globe,
  Shield,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Users,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Zap,
  DollarSign,
  ChevronDown,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { macroApi, councilApi, llmApi } from '@/lib/api'
import { cn } from '@/lib/utils'

export function MacroCouncilPage() {
  const [selectedDate, setSelectedDate] = useState<string | undefined>(undefined)

  // 날짜 목록 조회
  const { data: datesData } = useQuery({
    queryKey: ['macro-dates'],
    queryFn: macroApi.getDates,
    staleTime: 300000,
  })

  const { data: macroInsight, isLoading, refetch } = useQuery({
    queryKey: ['macro-insight', selectedDate],
    queryFn: () => macroApi.getInsight(selectedDate),
    refetchInterval: selectedDate ? false : 300000, // 선택된 날짜가 있으면 자동 갱신 안함
    staleTime: 180000,
  })

  const { data: councilReview } = useQuery({
    queryKey: ['council-review'],
    queryFn: councilApi.getDailyReview,
    refetchInterval: 600000,
    staleTime: 300000,
  })

  const { data: llmStats } = useQuery({
    queryKey: ['llm-stats'],
    queryFn: llmApi.getStats,
    staleTime: 300000,
  })

  const getSentimentBadge = (sentiment: string | undefined) => {
    if (!sentiment) return { color: 'bg-gray-500/20 text-gray-400', label: 'Unknown' }
    if (sentiment.includes('bullish')) return { color: 'bg-green-500/20 text-green-400', label: 'Bullish' }
    if (sentiment.includes('bearish')) return { color: 'bg-red-500/20 text-red-400', label: 'Bearish' }
    return { color: 'bg-yellow-500/20 text-yellow-400', label: 'Neutral' }
  }

  const getVixRegimeInfo = (regime: string | undefined) => {
    switch (regime) {
      case 'crisis':
        return { color: 'text-red-400', bgColor: 'bg-red-500/10', label: 'Crisis', icon: AlertTriangle }
      case 'elevated':
        return { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', label: 'Elevated', icon: AlertTriangle }
      case 'normal':
        return { color: 'text-blue-400', bgColor: 'bg-blue-500/10', label: 'Normal', icon: CheckCircle }
      case 'low_vol':
        return { color: 'text-green-400', bgColor: 'bg-green-500/10', label: 'Low Vol', icon: CheckCircle }
      default:
        return { color: 'text-gray-400', bgColor: 'bg-gray-500/10', label: 'Unknown', icon: BarChart3 }
    }
  }

  const getPoliticalRiskInfo = (level: string | undefined) => {
    switch (level) {
      case 'critical':
        return { color: 'bg-red-500 text-white', borderColor: 'border-red-500/50' }
      case 'high':
        return { color: 'bg-orange-500 text-white', borderColor: 'border-orange-500/50' }
      case 'medium':
        return { color: 'bg-yellow-500 text-black', borderColor: 'border-yellow-500/50' }
      case 'low':
        return { color: 'bg-green-500 text-white', borderColor: 'border-green-500/50' }
      default:
        return { color: 'bg-gray-500 text-white', borderColor: 'border-gray-500/50' }
    }
  }

  const sentimentBadge = getSentimentBadge(macroInsight?.sentiment)
  const vixInfo = getVixRegimeInfo(macroInsight?.vix_regime)
  const politicalRiskInfo = getPoliticalRiskInfo(macroInsight?.political_risk_level)
  const VixIcon = vixInfo.icon

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white flex items-center gap-3">
            <Globe className="w-7 h-7" />
            Macro Council
            {macroInsight?.insight_date && (
              <span className="text-sm font-normal text-muted-foreground ml-1">
                ({macroInsight.insight_date})
              </span>
            )}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            3현자 Council의 매크로 분석 및 트레이딩 권고
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* 날짜 선택 드롭다운 */}
          <div className="relative">
            <select
              value={selectedDate || ''}
              onChange={(e) => setSelectedDate(e.target.value || undefined)}
              className="appearance-none bg-[#1a1a1a] border border-white/10 rounded-md px-3 py-1.5 pr-8 text-sm text-white focus:outline-none focus:ring-2 focus:ring-accent/50 cursor-pointer"
            >
              <option value="">최신</option>
              {datesData?.dates?.map((date: string) => (
                <option key={date} value={date}>
                  {date}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            className="gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            새로고침
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent"></div>
        </div>
      ) : !macroInsight?.insight_date ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Globe className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
            <h3 className="text-lg font-medium mb-2">Council 분석 데이터 없음</h3>
            <p className="text-sm text-muted-foreground">
              오늘의 매크로 Council 분석이 아직 실행되지 않았습니다.
              <br />
              매일 오전 7:30 KST에 자동 실행됩니다.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* 1. Summary Cards Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Sentiment Card */}
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs text-muted-foreground">Council Sentiment</span>
                  <span className={cn('px-2 py-1 rounded text-xs font-medium', sentimentBadge.color)}>
                    {sentimentBadge.label}
                  </span>
                </div>
                <div className="text-3xl font-bold">{macroInsight.sentiment_score || '-'}</div>
                <p className="text-sm text-muted-foreground mt-1 capitalize">{macroInsight.sentiment || '-'}</p>
              </CardContent>
            </Card>

            {/* VIX Card */}
            <Card className={cn(vixInfo.bgColor)}>
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs text-muted-foreground">VIX (공포 지수)</span>
                  <VixIcon className={cn('w-5 h-5', vixInfo.color)} />
                </div>
                <div className={cn('text-3xl font-bold', vixInfo.color)}>
                  {Number(macroInsight.vix_value || 0).toFixed(1)}
                </div>
                <p className={cn('text-sm mt-1 font-medium', vixInfo.color)}>{vixInfo.label}</p>
              </CardContent>
            </Card>

            {/* Position Size Card */}
            <Card className="bg-blue-500/5 border-blue-500/20">
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs text-muted-foreground">포지션 크기 권고</span>
                  <BarChart3 className="w-5 h-5 text-blue-400" />
                </div>
                <div className="text-3xl font-bold text-blue-400">
                  {macroInsight.position_size_pct || 100}%
                </div>
                <p className="text-sm text-muted-foreground mt-1">기본 대비</p>
              </CardContent>
            </Card>

            {/* Stop Loss Card */}
            <Card className="bg-orange-500/5 border-orange-500/20">
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs text-muted-foreground">손절폭 조정</span>
                  <Shield className="w-5 h-5 text-orange-400" />
                </div>
                <div className="text-3xl font-bold text-orange-400">
                  {macroInsight.stop_loss_adjust_pct || 100}%
                </div>
                <p className="text-sm text-muted-foreground mt-1">기본 대비</p>
              </CardContent>
            </Card>
          </div>

          {/* 2. 글로벌 시장 현황 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Globe className="w-4 h-4 text-muted-foreground" />
                글로벌 시장 현황
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Left: 글로벌 지표 */}
                <div>
                  <p className="text-xs text-muted-foreground mb-3 font-medium">글로벌 지표</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">USD/KRW</p>
                      <p className="text-xl font-semibold">{Number(macroInsight.usd_krw || 0).toFixed(1)}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">KOSPI</p>
                      <p className="text-xl font-semibold">{Number(macroInsight.kospi_index || 0).toFixed(0)}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">KOSDAQ</p>
                      <p className="text-xl font-semibold">{Number(macroInsight.kosdaq_index || 0).toFixed(0)}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">데이터 완성도</p>
                      <p className="text-xl font-semibold">{macroInsight.data_completeness_pct || '-'}%</p>
                    </div>
                  </div>
                </div>

                {/* Right: 투자자별 순매수 */}
                <div>
                  <p className="text-xs text-muted-foreground mb-3 font-medium">투자자별 순매수 (KOSPI, 억원)</p>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <span className="text-sm">외국인</span>
                      <span className={cn(
                        'text-lg font-semibold',
                        (macroInsight.kospi_foreign_net || 0) >= 0 ? 'text-profit-positive' : 'text-profit-negative'
                      )}>
                        {(macroInsight.kospi_foreign_net || 0) >= 0 ? '+' : ''}
                        {(macroInsight.kospi_foreign_net || 0).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <span className="text-sm">기관</span>
                      <span className={cn(
                        'text-lg font-semibold',
                        (macroInsight.kospi_institutional_net || 0) >= 0 ? 'text-profit-positive' : 'text-profit-negative'
                      )}>
                        {(macroInsight.kospi_institutional_net || 0) >= 0 ? '+' : ''}
                        {(macroInsight.kospi_institutional_net || 0).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <span className="text-sm">개인</span>
                      <span className={cn(
                        'text-lg font-semibold',
                        (macroInsight.kospi_retail_net || 0) >= 0 ? 'text-profit-positive' : 'text-profit-negative'
                      )}>
                        {(macroInsight.kospi_retail_net || 0) >= 0 ? '+' : ''}
                        {(macroInsight.kospi_retail_net || 0).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* 3. 트레이딩 전략 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Zap className="w-4 h-4 text-muted-foreground" />
                트레이딩 전략
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Regime Badge + Trading Reasoning */}
              {(macroInsight.regime_hint || macroInsight.trading_reasoning) && (
                <div className="flex items-start gap-3 p-3 rounded-lg bg-white/[0.02] border border-white/5">
                  {macroInsight.regime_hint && (
                    <span className="shrink-0 px-2.5 py-1 rounded text-xs font-bold bg-accent/20 text-accent">
                      {macroInsight.regime_hint}
                    </span>
                  )}
                  {macroInsight.trading_reasoning && (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {macroInsight.trading_reasoning}
                    </p>
                  )}
                </div>
              )}

              {/* 2x2 Grid: Strategies + Sectors */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {/* 허용 전략 */}
                <div className="p-3 rounded-lg bg-green-500/5 border border-green-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle className="w-4 h-4 text-green-400" />
                    <span className="text-sm font-medium text-green-400">허용 전략</span>
                  </div>
                  {macroInsight.strategies_to_favor?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {macroInsight.strategies_to_favor.map((s: string, i: number) => (
                        <span
                          key={i}
                          className="px-2 py-1 text-xs bg-green-500/20 text-green-400 rounded-md"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">지정된 전략 없음</p>
                  )}
                </div>

                {/* 회피 전략 */}
                <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <XCircle className="w-4 h-4 text-red-400" />
                    <span className="text-sm font-medium text-red-400">회피 전략</span>
                  </div>
                  {macroInsight.strategies_to_avoid?.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {macroInsight.strategies_to_avoid.map((s: string, i: number) => (
                        <span
                          key={i}
                          className="px-2 py-1 text-xs bg-red-500/20 text-red-400 rounded-md"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">지정된 전략 없음</p>
                  )}
                </div>

                {/* 유망 섹터 */}
                <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <TrendingUp className="w-4 h-4 text-blue-400" />
                    <span className="text-xs font-medium text-blue-400">유망 섹터</span>
                  </div>
                  {macroInsight.sectors_to_favor?.length > 0 ? (
                    <div className="space-y-1">
                      {macroInsight.sectors_to_favor.slice(0, 5).map((s: string, i: number) => (
                        <span key={i} className="block text-xs text-blue-400/80">{s}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">-</p>
                  )}
                </div>

                {/* 회피 섹터 */}
                <div className="p-3 rounded-lg bg-gray-500/5 border border-gray-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <TrendingDown className="w-4 h-4 text-gray-400" />
                    <span className="text-xs font-medium text-gray-400">회피 섹터</span>
                  </div>
                  {macroInsight.sectors_to_avoid?.length > 0 ? (
                    <div className="space-y-1">
                      {macroInsight.sectors_to_avoid.slice(0, 5).map((s: string, i: number) => (
                        <span key={i} className="block text-xs text-gray-400/80">{s}</span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">-</p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* 4. 리스크 & 기회 분석 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Shield className="w-4 h-4 text-muted-foreground" />
                리스크 & 기회 분석
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Political Risk Banner */}
              <div className={cn('flex items-start gap-3 p-3 rounded-lg border', politicalRiskInfo.borderColor)}>
                <span className={cn('shrink-0 px-2.5 py-1 rounded text-xs font-bold', politicalRiskInfo.color)}>
                  {macroInsight.political_risk_level?.toUpperCase() || 'UNKNOWN'}
                </span>
                <div>
                  <p className="text-xs text-muted-foreground mb-1">정치/지정학적 리스크</p>
                  {macroInsight.political_risk_summary ? (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {macroInsight.political_risk_summary}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground">요약 없음</p>
                  )}
                </div>
              </div>

              {/* 2-col: Risk + Opportunity */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 리스크 요인 */}
                <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                  <div className="flex items-center gap-2 mb-3">
                    <AlertTriangle className="w-4 h-4 text-red-400" />
                    <span className="text-sm font-medium text-red-400">리스크 요인</span>
                  </div>
                  {macroInsight.risk_factors?.length > 0 ? (
                    <ul className="space-y-2">
                      {macroInsight.risk_factors.map((factor: string, i: number) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                          <span className="text-red-400 mt-0.5">•</span>
                          {factor}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">리스크 요인 없음</p>
                  )}
                </div>

                {/* 기회 요인 */}
                <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                  <div className="flex items-center gap-2 mb-3">
                    <TrendingUp className="w-4 h-4 text-green-400" />
                    <span className="text-sm font-medium text-green-400">기회 요인</span>
                  </div>
                  {macroInsight.opportunity_factors?.length > 0 ? (
                    <ul className="space-y-2">
                      {macroInsight.opportunity_factors.map((factor: string, i: number) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                          <span className="text-green-400 mt-0.5">•</span>
                          {factor}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">기회 요인 없음</p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* 5. 3현자 Council 리뷰 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Users className="w-4 h-4 text-muted-foreground" />
                3현자 Council 리뷰
              </CardTitle>
            </CardHeader>
            <CardContent>
              {councilReview?.sages?.length > 0 ? (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {councilReview.sages.map((sage: any) => (
                      <div
                        key={sage.name}
                        className="p-4 rounded-lg bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors"
                      >
                        <div className="flex items-center gap-3 mb-3">
                          <span className="text-2xl">{sage.icon}</span>
                          <div>
                            <p className="font-medium">{sage.name}</p>
                            <p className="text-xs text-muted-foreground">{sage.role}</p>
                          </div>
                        </div>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                          {sage.review}
                        </p>
                      </div>
                    ))}
                  </div>
                  {councilReview.consensus && (
                    <div className="mt-4 p-4 rounded-lg bg-blue-500/5 border border-blue-500/20">
                      <div className="flex items-center gap-2 mb-2">
                        <CheckCircle className="w-4 h-4 text-blue-400" />
                        <span className="text-sm font-medium text-blue-400">Council 합의 사항</span>
                      </div>
                      <p className="text-sm text-muted-foreground">{councilReview.consensus}</p>
                    </div>
                  )}
                </>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5">
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-2xl">👑</span>
                      <div>
                        <p className="font-medium">Jennie (Gemini)</p>
                        <p className="text-xs text-muted-foreground">수석 심판 (Chief Judge)</p>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">오늘의 리뷰가 아직 생성되지 않았습니다.</p>
                  </div>
                  <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5">
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-2xl">🔍</span>
                      <div>
                        <p className="font-medium">Minji (Claude)</p>
                        <p className="text-xs text-muted-foreground">리스크 분석가 (Risk Analyst)</p>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">시스템 분석을 기다리고 있습니다.</p>
                  </div>
                  <div className="p-4 rounded-lg bg-white/[0.02] border border-white/5">
                    <div className="flex items-center gap-3 mb-3">
                      <span className="text-2xl">📈</span>
                      <div>
                        <p className="font-medium">Junho (GPT-4o)</p>
                        <p className="text-xs text-muted-foreground">전략가 (Strategist)</p>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">전략 검토를 준비 중입니다.</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Footer: Source + Cost + LLM Usage (inline) */}
          <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
            <div className="flex items-center gap-4">
              {macroInsight.source_channel && (
                <span>출처: <span className="text-blue-400">@{macroInsight.source_channel}</span></span>
              )}
              {macroInsight.source_analyst && (
                <span>분석가: <span className="text-white">{macroInsight.source_analyst}</span></span>
              )}
            </div>
            <div className="flex items-center gap-4">
              {llmStats?.macro_council && (llmStats.macro_council.calls > 0 || llmStats.macro_council.tokens > 0) && (
                <div className="flex items-center gap-1">
                  <Zap className="w-3 h-3" />
                  <span>LLM {llmStats.macro_council.calls}회 / {llmStats.macro_council.tokens.toLocaleString()} tokens</span>
                </div>
              )}
              {macroInsight.council_cost_usd && (
                <div className="flex items-center gap-1">
                  <DollarSign className="w-3 h-3" />
                  <span>
                    ${Number(macroInsight.council_cost_usd)?.toFixed(3)} (~{Math.round(Number(macroInsight.council_cost_usd || 0) * 1450)}원)
                  </span>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default MacroCouncilPage
