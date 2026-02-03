import { useQuery } from '@tanstack/react-query'
import {
  Globe,
  Shield,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Users,
  Calendar,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Zap,
  DollarSign,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { macroApi, councilApi } from '@/lib/api'
import { cn } from '@/lib/utils'

export function MacroCouncilPage() {
  const { data: macroInsight, isLoading, refetch } = useQuery({
    queryKey: ['macro-insight'],
    queryFn: macroApi.getInsight,
    refetchInterval: 300000, // 5분
    staleTime: 180000,
  })

  const { data: councilReview } = useQuery({
    queryKey: ['council-review'],
    queryFn: councilApi.getDailyReview,
    refetchInterval: 600000,
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
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            3현자 Council의 매크로 분석 및 트레이딩 권고
          </p>
        </div>
        <div className="flex items-center gap-3">
          {macroInsight?.insight_date && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Calendar className="w-4 h-4" />
              {macroInsight.insight_date}
            </div>
          )}
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
          {/* Summary Cards Row */}
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
                  {macroInsight.vix_value?.toFixed(1) || '-'}
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

          {/* Main Content Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column - Global Indicators */}
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm font-medium">
                    <Globe className="w-4 h-4 text-muted-foreground" />
                    글로벌 지표
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">USD/KRW</p>
                      <p className="text-xl font-semibold">{macroInsight.usd_krw?.toFixed(1) || '-'}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">KOSPI</p>
                      <p className="text-xl font-semibold">{macroInsight.kospi_index?.toFixed(0) || '-'}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">KOSDAQ</p>
                      <p className="text-xl font-semibold">{macroInsight.kosdaq_index?.toFixed(0) || '-'}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                      <p className="text-xs text-muted-foreground mb-1">데이터 완성도</p>
                      <p className="text-xl font-semibold">{macroInsight.data_completeness_pct || '-'}%</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Investor Trading Data */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm font-medium">
                    <Users className="w-4 h-4 text-muted-foreground" />
                    투자자별 순매수 (KOSPI, 억원)
                  </CardTitle>
                </CardHeader>
                <CardContent>
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
                </CardContent>
              </Card>

              {/* Council Cost */}
              {macroInsight.council_cost_usd && (
                <Card>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <DollarSign className="w-4 h-4 text-muted-foreground" />
                        <span className="text-sm text-muted-foreground">Council 분석 비용</span>
                      </div>
                      <span className="text-sm font-medium">
                        ${macroInsight.council_cost_usd?.toFixed(3)} (~{Math.round((macroInsight.council_cost_usd || 0) * 1450)}원)
                      </span>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Middle Column - Trading Recommendations */}
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-sm font-medium">
                    <Zap className="w-4 h-4 text-muted-foreground" />
                    트레이딩 권고
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Strategies to Favor */}
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

                  {/* Strategies to Avoid */}
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

                  {/* Sectors */}
                  <div className="grid grid-cols-2 gap-3">
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

              {/* Trading Reasoning */}
              {macroInsight.trading_reasoning && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Council 판단 근거</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {macroInsight.trading_reasoning}
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right Column - Risk & Council */}
            <div className="space-y-4">
              {/* Political Risk */}
              <Card className={cn('border', politicalRiskInfo.borderColor)}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between text-sm font-medium">
                    <div className="flex items-center gap-2">
                      <Shield className="w-4 h-4 text-muted-foreground" />
                      정치/지정학적 리스크
                    </div>
                    <span className={cn('px-2.5 py-1 rounded text-xs font-bold', politicalRiskInfo.color)}>
                      {macroInsight.political_risk_level?.toUpperCase() || 'UNKNOWN'}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {macroInsight.political_risk_summary ? (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {macroInsight.political_risk_summary}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground">정치 리스크 요약 없음</p>
                  )}
                </CardContent>
              </Card>

              {/* Risk Factors */}
              {macroInsight.risk_factors?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm font-medium">
                      <AlertTriangle className="w-4 h-4 text-yellow-400" />
                      리스크 요인
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {macroInsight.risk_factors.map((factor: string, i: number) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                          <span className="text-yellow-400 mt-0.5">•</span>
                          {factor}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {/* Key Themes */}
              {macroInsight.key_themes?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">핵심 테마</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {macroInsight.key_themes.map((theme: string, i: number) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 text-xs bg-purple-500/20 text-purple-400 rounded-md"
                        >
                          {theme}
                        </span>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Key Stocks */}
              {macroInsight.key_stocks?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">주목 종목</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {macroInsight.key_stocks.map((stock: string, i: number) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 text-xs bg-accent/20 text-accent rounded-md font-medium"
                        >
                          {stock}
                        </span>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>

          {/* 3 Sages Council Review Section */}
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
        </>
      )}
    </div>
  )
}

export default MacroCouncilPage
