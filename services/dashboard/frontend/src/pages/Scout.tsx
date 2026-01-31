import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  Target,
  Scale,
  Gavel,
  CheckCircle2,
  Clock,
  TrendingUp,
  TrendingDown,
  Sparkles,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { scoutApi, watchlistApi } from '@/lib/api'
import {
  formatRelativeTime,
  getGradeColor,
  getGradeBgColor,
  cn,
} from '@/lib/utils'

const phaseIcons = [Target, Scale, Gavel]
const phaseNames = ['Hunter Scout', 'Bull vs Bear Debate', 'Final Judge']
const phaseDescriptions = [
  'gpt-oss:20b (Local LLM)로 정밀한 1차 필터링',
  'gpt-oss:20b로 Bull vs Bear 심층 토론',
  'gpt-oss:20b로 최종 의사결정 및 등급 부여',
]
const phaseLLMs = ['gpt-oss:20b', 'gpt-oss:20b', 'gpt-oss:20b']

export function ScoutPage() {
  const { data: status } = useQuery({
    queryKey: ['scout-status'],
    queryFn: scoutApi.getStatus,
    refetchInterval: 30000, // 30초 (5초 → 30초, 83% 감소)
    staleTime: 15000,
  })

  const { data: results } = useQuery({
    queryKey: ['scout-results'],
    queryFn: scoutApi.getResults,
    refetchInterval: 60000, // 1분 (30초 → 1분)
    staleTime: 30000,
  })

  const { data: watchlist } = useQuery({
    queryKey: ['watchlist'],
    queryFn: () => watchlistApi.getAll(20),
    staleTime: 60000,
  })

  const isRunning = status?.status === 'running'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <Brain className="w-8 h-8 text-muted-foreground" />
            <div>
              <h1 className="text-2xl font-semibold text-white">
                Scout-Debate-Judge Pipeline
              </h1>
              <p className="text-xs text-blue-400 font-medium">
                The Slow Brain of Prime Jennie
              </p>
            </div>
          </div>
          <p className="text-sm text-muted-foreground">
            3단계 Multi-Agent LLM이 신중하게 종목을 선별합니다 •
            <span className="text-blue-400 ml-1">1시간마다 시장 상황 재평가</span>
          </p>
        </div>
        {isRunning ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/30">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-xs font-medium text-blue-400">분석 중</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-green-500/10 border border-green-500/30">
            <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
            <span className="text-xs font-medium text-green-400">대기 중</span>
          </div>
        )}
      </div>

      {/* Pipeline Visualization */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="w-4 h-4 text-muted-foreground" />
            3-Phase LLM Pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="relative">
            {/* Connection Line */}
            <div className="absolute top-10 left-0 right-0 h-px bg-white/10" />

            {/* Phases */}
            <div className="grid grid-cols-3 gap-3 relative">
              {[1, 2, 3].map((phase) => {
                const PhaseIcon = phaseIcons[phase - 1]
                const isActive = status?.phase === phase
                const isComplete = status?.phase > phase
                const isPending = status?.phase < phase

                return (
                  <div
                    key={phase}
                    className={cn(
                      'relative p-4 rounded-lg border transition-all',
                      isActive && 'border-blue-500/50 bg-blue-500/5',
                      isComplete && 'border-green-500/30 bg-green-500/5',
                      isPending && 'border-white/5 bg-white/[0.02]'
                    )}
                  >
                    {/* Phase Number Badge */}
                    <div
                      className={cn(
                        'absolute -top-2 -left-2 w-6 h-6 rounded-full flex items-center justify-center font-medium text-xs',
                        isActive && 'bg-blue-500 text-white',
                        isComplete && 'bg-green-500 text-white',
                        isPending && 'bg-white/10 text-muted-foreground'
                      )}
                    >
                      {isComplete ? <CheckCircle2 className="w-4 h-4" /> : phase}
                    </div>

                    {/* Content */}
                    <div className="flex flex-col items-center text-center">
                      <div
                        className={cn(
                          'w-12 h-12 rounded-lg flex items-center justify-center mb-3',
                          isActive && 'bg-blue-500/10',
                          isComplete && 'bg-green-500/10',
                          isPending && 'bg-white/5'
                        )}
                      >
                        <PhaseIcon
                          className={cn(
                            'w-6 h-6',
                            isActive && 'text-blue-400',
                            isComplete && 'text-green-400',
                            isPending && 'text-muted-foreground'
                          )}
                        />
                      </div>

                      <h3 className="text-sm font-medium mb-1">{phaseNames[phase - 1]}</h3>
                      <p className="text-xs text-muted-foreground mb-2 line-clamp-2">
                        {phaseDescriptions[phase - 1]}
                      </p>

                      {/* LLM Badge */}
                      <div className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-xs font-mono text-muted-foreground">
                        {phaseLLMs[phase - 1]}
                      </div>

                      {/* Stats */}
                      <div className="mt-3 text-xs">
                        {phase === 1 && (
                          <span className={cn(isActive && 'text-blue-400', isComplete && 'text-green-400')}>
                            {status?.passed_phase1 || 0}개 통과
                          </span>
                        )}
                        {phase === 2 && (
                          <span className={cn(isActive && 'text-blue-400', isComplete && 'text-green-400')}>
                            {status?.passed_phase2 || 0}개 토론
                          </span>
                        )}
                        {phase === 3 && (
                          <span className={cn(isActive && 'text-blue-400', isComplete && 'text-green-400')}>
                            {status?.final_selected || 0}개 선정
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Current Stock */}
          {status?.current_stock && isRunning && (
            <div className="mt-4 p-3 rounded-lg bg-white/[0.02] border border-white/5">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                <span className="text-xs text-muted-foreground">현재 분석 중:</span>
                <span className="text-sm font-medium">{status.current_stock}</span>
              </div>
              {status.progress > 0 && (
                <div className="mt-2">
                  <div className="h-1 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-blue-500 transition-all"
                      style={{ width: `${status.progress}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground mt-1 text-right">
                    {status.progress.toFixed(0)}% 완료
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Last Updated */}
          {status?.last_updated && (
            <p className="mt-3 text-xs text-muted-foreground text-right">
              마지막 업데이트: {formatRelativeTime(status.last_updated)}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Results Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Selected Stocks */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <CheckCircle2 className="w-4 h-4 text-green-400" />
              선정된 종목 (Judge 통과)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {results?.results?.filter((r: any) => r.selected)?.length === 0 && (
              <p className="text-center text-muted-foreground py-8 text-sm">
                아직 선정된 종목이 없습니다
              </p>
            )}
            <div className="space-y-2">
              {results?.results
                ?.filter((r: any) => r.selected)
                ?.map((result: any) => (
                  <div
                    key={result.stock_code}
                    className="p-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.04] border border-white/5 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className={cn(
                            'w-8 h-8 rounded-lg flex items-center justify-center font-medium text-sm border',
                            getGradeBgColor(result.grade)
                          )}
                        >
                          <span className={getGradeColor(result.grade)}>
                            {result.grade}
                          </span>
                        </div>
                        <div>
                          <h4 className="text-sm font-medium">{result.stock_name}</h4>
                          <p className="text-xs text-muted-foreground font-mono">
                            {result.stock_code}
                          </p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="font-mono text-sm text-green-400">
                          {result.final_score}점
                        </p>
                        <p className="text-xs text-muted-foreground">
                          최종 점수
                        </p>
                      </div>
                    </div>
                    {result.judge_reason && (
                      <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                        {result.judge_reason}
                      </p>
                    )}
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>

        {/* Watchlist with LLM Scores */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Target className="w-4 h-4 text-blue-400" />
              Watchlist LLM 점수
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 max-h-[400px] overflow-y-auto">
              {watchlist?.map((item: any) => (
                <div
                  key={item.stock_code}
                  className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02] transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        'w-6 h-6 rounded flex items-center justify-center text-xs font-medium border',
                        getGradeBgColor(item.llm_grade || 'C')
                      )}
                    >
                      <span className={getGradeColor(item.llm_grade || 'C')}>
                        {item.llm_grade || '-'}
                      </span>
                    </div>
                    <div>
                      <p className="text-sm font-medium">{item.stock_name}</p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {item.stock_code}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <p className="font-mono text-xs">
                        {item.llm_score ? `${item.llm_score}점` : '-'}
                      </p>
                    </div>
                    {item.news_sentiment !== null && (
                      <div className="flex items-center gap-1">
                        {item.news_sentiment >= 50 ? (
                          <TrendingUp className="w-3 h-3 text-green-400" />
                        ) : (
                          <TrendingDown className="w-3 h-3 text-red-400" />
                        )}
                        <span className="text-xs font-mono">
                          {item.news_sentiment?.toFixed(0)}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pipeline Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="p-4 text-center">
            <Clock className="w-5 h-5 mx-auto text-muted-foreground mb-2" />
            <p className="text-xl font-semibold">{status?.total_candidates || 200}</p>
            <p className="text-xs text-muted-foreground">전체 후보</p>
            <p className="text-xs text-blue-400 mt-1">KOSPI 200</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <Target className="w-5 h-5 mx-auto text-muted-foreground mb-2" />
            <p className="text-xl font-semibold">{status?.passed_phase1 || 0}</p>
            <p className="text-xs text-muted-foreground">Phase 1 통과</p>
            <p className="text-xs text-muted-foreground mt-1">gpt-oss:20b</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <Scale className="w-5 h-5 mx-auto text-muted-foreground mb-2" />
            <p className="text-xl font-semibold">{status?.passed_phase2 || 0}</p>
            <p className="text-xs text-muted-foreground">Phase 2 토론</p>
            <p className="text-xs text-muted-foreground mt-1">Bull vs Bear</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <Gavel className="w-5 h-5 mx-auto text-muted-foreground mb-2" />
            <p className="text-xl font-semibold">{status?.final_selected || 0}</p>
            <p className="text-xs text-muted-foreground">최종 선정</p>
            <p className="text-xs text-green-400 mt-1">→ Watchlist</p>
          </CardContent>
        </Card>
      </div>

      {/* Slow Brain Philosophy */}
      <Card className="border-dashed">
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center">
                <Brain className="w-5 h-5 text-muted-foreground" />
              </div>
              <div>
                <h4 className="text-sm font-medium">Slow Brain</h4>
                <p className="text-xs text-muted-foreground">신중하게 종목 선별 • UPSERT로 누적 관리</p>
              </div>
            </div>
            <div className="text-center px-4">
              <p className="text-xs text-muted-foreground">→</p>
            </div>
            <div className="flex items-center gap-3">
              <div>
                <h4 className="text-sm font-medium text-right">Fast Hand</h4>
                <p className="text-xs text-muted-foreground">가격 변동 시 빠른 체결</p>
              </div>
              <div className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center">
                <Target className="w-5 h-5 text-muted-foreground" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
