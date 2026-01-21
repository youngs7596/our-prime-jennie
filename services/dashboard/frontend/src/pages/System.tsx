import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Server,
  Database,
  MessageSquare,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  RefreshCw,
  Container,
  Activity,
  X,
  Terminal,
  Settings,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { systemApi, configApi } from '@/lib/api'
import { formatRelativeTime, cn } from '@/lib/utils'
import { toast } from 'react-hot-toast'

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}



const getStatusIcon = (status: string) => {
  switch (status.toLowerCase()) {
    case 'active':
    case 'running':
    case 'up':
    case 'healthy':
      return <CheckCircle className="w-4 h-4 text-profit-positive" />
    case 'inactive':
    case 'stopped':
    case 'down':
      return <XCircle className="w-4 h-4 text-muted-foreground" />
    case 'error':
    case 'unhealthy':
      return <AlertCircle className="w-4 h-4 text-profit-negative" />
    default:
      return <Clock className="w-4 h-4 text-jennie-gold" />
  }
}

export function SystemPage() {
  const [selectedContainer, setSelectedContainer] = useState<string | null>(null)
  const queryClient = useQueryClient()

  // 1. Docker Status
  const { data: dockerStatus, isLoading: dockerLoading, refetch: refetchDocker } = useQuery({
    queryKey: ['system-docker'],
    queryFn: systemApi.getDocker,
    refetchInterval: 5000,
  })

  // 2. RabbitMQ Status
  const { data: rabbitmqStatus, refetch: refetchRabbitMQ } = useQuery({
    queryKey: ['system-rabbitmq'],
    queryFn: systemApi.getRabbitMQ,
    refetchInterval: 5000,
  })

  // 3. Realtime Monitor Status
  const { data: realtimeDetails, isLoading: realtimeLoading, refetch: refetchRealtime } = useQuery({
    queryKey: ['system-realtime'],
    queryFn: systemApi.getRealtimeMonitor,
    refetchInterval: 1000,
  })

  // 4. Container Logs
  const { data: containerLogs, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ['container-logs', selectedContainer],
    queryFn: () => systemApi.getContainerLogs(selectedContainer!),
    enabled: !!selectedContainer,
    refetchInterval: 5000,
  })

  const { data: configData } = useQuery({
    queryKey: ['config-list'],
    queryFn: configApi.list,
    refetchInterval: 60000,
  })

  // 운영 설정 업데이트 mutation
  const updateConfigMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: boolean }) =>
      configApi.update(key, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config-list'] })
      toast.success('설정이 저장되었습니다')
    },
    onError: (error) => {
      toast.error('설정 저장 실패: ' + (error as Error).message)
    },
  })

  // DISABLE_MARKET_OPEN_CHECK 값 추출
  const disableMarketCheck = Array.isArray(configData)
    ? configData.find((c: { key: string; value: boolean }) => c.key === 'DISABLE_MARKET_OPEN_CHECK')?.value ?? false
    : false

  const handleRefreshAll = () => {
    refetchDocker()
    refetchRabbitMQ()
    refetchRealtime()
  }

  const handleContainerClick = (containerName: string) => {
    setSelectedContainer(containerName)
  }

  const closeLogModal = () => {
    setSelectedContainer(null)
  }

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-display font-bold flex items-center gap-3">
            <Activity className="w-8 h-8 text-jennie-blue" />
            System Status
          </h1>
          <p className="text-muted-foreground mt-1">
            WSL2 + Docker 환경의 서비스 상태를 모니터링합니다
          </p>
        </div>
        <Button variant="outline" onClick={handleRefreshAll} className="gap-2">
          <RefreshCw className="w-4 h-4" />
          새로고침
        </Button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-profit-positive/20">
                <Container className="w-5 h-5 text-profit-positive" />
              </div>
              <div>
                <p className="text-2xl font-bold">{dockerStatus?.count || 0}</p>
                <p className="text-xs text-muted-foreground">실행 중 컨테이너</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-jennie-pink/20">
                <MessageSquare className="w-5 h-5 text-jennie-pink" />
              </div>
              <div>
                <p className="text-2xl font-bold">
                  {rabbitmqStatus?.queues?.reduce((sum: number, q: any) => sum + (q.messages || 0), 0) || 0}
                </p>
                <p className="text-xs text-muted-foreground">대기 메시지</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-jennie-blue/20">
                <Database className="w-5 h-5 text-jennie-blue" />
              </div>
              <div>
                <p className="text-2xl font-bold">MariaDB</p>
                <p className="text-xs text-muted-foreground">Primary DB (WSL2)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Real-time Watcher Status (New) */}
      <motion.div variants={itemVariants}>
        <Card className="border-jennie-gold/30 bg-jennie-gold/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-jennie-gold">
              <Activity className="w-5 h-5 animate-pulse" />
              Real-time Watcher Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            {realtimeLoading ? (
              <div className="h-12 w-full bg-white/5 animate-pulse rounded" />
            ) : (!realtimeDetails || realtimeDetails.status === 'offline') ? (
              <div className="text-center py-4 text-muted-foreground">
                <p>⚠️ 모니터링 데이터 없음 (Price Monitor가 실행 중인지 확인하세요)</p>
                {realtimeDetails?.message && <p className="text-xs mt-1">{realtimeDetails.message}</p>}
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
                <div className="p-3 bg-black/20 rounded-lg">
                  <p className="text-xs text-muted-foreground mb-1">🔥 Hot Watchlist</p>
                  <p className="text-lg font-bold text-white">{realtimeDetails.metrics?.hot_watchlist_size ?? 0}</p>
                </div>
                <div className="p-3 bg-black/20 rounded-lg">
                  <p className="text-xs text-muted-foreground mb-1">📶 Tick Count</p>
                  <p className="text-lg font-bold text-white">{realtimeDetails.metrics?.tick_count ?? 0}</p>
                </div>
                <div className="p-3 bg-black/20 rounded-lg">
                  <p className="text-xs text-muted-foreground mb-1">🔔 Signals</p>
                  <p className="text-lg font-bold text-jennie-gold">{realtimeDetails.metrics?.signal_count ?? 0}</p>
                </div>
                <div className="p-3 bg-black/20 rounded-lg">
                  <p className="text-xs text-muted-foreground mb-1">📊 Market Regime</p>
                  <p className="text-lg font-bold text-jennie-blue">{realtimeDetails.metrics?.market_regime ?? 'UNK'}</p>
                </div>
                <div className="p-3 bg-black/20 rounded-lg">
                  <p className="text-xs text-muted-foreground mb-1">⏱️ Last Active</p>
                  <p className="text-xs font-mono mt-1 text-white">
                    {realtimeDetails.metrics?.updated_at ?
                      formatRelativeTime(realtimeDetails.metrics.updated_at) : '-'}
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Docker Containers */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Container className="w-5 h-5 text-jennie-blue" />
              Docker Containers (WSL2)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dockerLoading ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-12 rounded-lg bg-white/5 animate-pulse" />
                ))}
              </div>
            ) : dockerStatus?.error ? (
              <div className="text-center py-8 text-muted-foreground">
                <AlertCircle className="w-8 h-8 mx-auto mb-2 text-profit-negative" />
                <p>Docker 상태를 가져올 수 없습니다</p>
                <p className="text-xs mt-1">{dockerStatus.error}</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {dockerStatus?.containers?.map((container: any) => (
                  <div
                    key={container.ID}
                    onClick={() => handleContainerClick(container.Names)}
                    className="p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-sm truncate flex items-center gap-2">
                        {container.Names}
                        <Terminal className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-jennie-blue" />
                      </span>
                      {getStatusIcon(container.Status?.includes('Up') ? 'running' : 'stopped')}
                    </div>
                    <p className="text-xs text-muted-foreground truncate">
                      {container.Image}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                      {container.Status}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* RabbitMQ Queues */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-jennie-pink" />
              RabbitMQ Queues
            </CardTitle>
          </CardHeader>
          <CardContent>
            {rabbitmqStatus?.error ? (
              <div className="text-center py-8 text-muted-foreground">
                <AlertCircle className="w-8 h-8 mx-auto mb-2 text-profit-negative" />
                <p>RabbitMQ 상태를 가져올 수 없습니다</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {rabbitmqStatus?.queues?.map((queue: any) => (
                  <div
                    key={queue.name}
                    className="p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm truncate">{queue.name}</span>
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded-full text-xs font-medium',
                          queue.messages > 0
                            ? 'bg-jennie-gold/20 text-jennie-gold'
                            : 'bg-white/10 text-muted-foreground'
                        )}
                      >
                        {queue.messages || 0}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Environment Info */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="w-5 h-5 text-muted-foreground" />
              Environment
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 rounded-lg bg-white/5">
                <p className="text-xs text-muted-foreground">Platform</p>
                <p className="font-medium">WSL2 (Ubuntu)</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5">
                <p className="text-xs text-muted-foreground">Orchestration</p>
                <p className="font-medium">Docker Compose</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5">
                <p className="text-xs text-muted-foreground">Primary DB</p>
                <p className="font-medium">MariaDB (WSL2)</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Operations Settings */}
      <motion.div variants={itemVariants}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="w-5 h-5 text-jennie-gold" />
              운영 설정
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {/* DISABLE_MARKET_OPEN_CHECK 토글 */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
                <div>
                  <h4 className="font-semibold text-sm">장 시간 체크 비활성화</h4>
                  <p className="text-xs text-muted-foreground mt-1">
                    활성화 시 장 운영 시간(09:00~15:30) 외에도 서비스가 실행됩니다.
                  </p>
                </div>
                <button
                  onClick={() => {
                    updateConfigMutation.mutate({
                      key: 'DISABLE_MARKET_OPEN_CHECK',
                      value: !disableMarketCheck,
                    })
                  }}
                  disabled={updateConfigMutation.isPending}
                  className={cn(
                    'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
                    disableMarketCheck ? 'bg-jennie-gold' : 'bg-white/20',
                    updateConfigMutation.isPending && 'opacity-50 cursor-not-allowed'
                  )}
                >
                  <span
                    className={cn(
                      'inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform',
                      disableMarketCheck ? 'translate-x-6' : 'translate-x-1'
                    )}
                  />
                </button>
              </div>
              {/* 현재 상태 표시 */}
              <div className="text-xs text-muted-foreground text-center">
                현재 상태: {disableMarketCheck ? (
                  <span className="text-jennie-gold font-medium">장외 시간 실행 허용 (테스트 모드)</span>
                ) : (
                  <span className="text-profit-positive font-medium">장 시간만 실행 (정상 운영)</span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Log Viewer Modal */}
      <AnimatePresence>
        {selectedContainer && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={closeLogModal}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-card border border-white/10 rounded-xl w-full max-w-4xl max-h-[80vh] overflow-hidden shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="flex items-center justify-between p-4 border-b border-white/10 bg-white/5">
                <div className="flex items-center gap-3">
                  <Terminal className="w-5 h-5 text-jennie-blue" />
                  <h3 className="font-semibold text-lg">{selectedContainer}</h3>
                  <span className="text-xs text-muted-foreground bg-white/10 px-2 py-1 rounded">
                    실시간 로그 (5초 갱신)
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => refetchLogs()}
                    className="gap-1"
                  >
                    <RefreshCw className={cn("w-4 h-4", logsLoading && "animate-spin")} />
                    새로고침
                  </Button>
                  <Button variant="ghost" size="sm" onClick={closeLogModal}>
                    <X className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              {/* Log Content */}
              <div className="p-4 overflow-auto max-h-[60vh] font-mono text-sm bg-black/50">
                {logsLoading && !containerLogs ? (
                  <div className="flex items-center justify-center py-8 text-muted-foreground">
                    <RefreshCw className="w-5 h-5 animate-spin mr-2" />
                    로그를 불러오는 중...
                  </div>
                ) : containerLogs?.error ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <AlertCircle className="w-8 h-8 mx-auto mb-2 text-profit-negative" />
                    <p>로그를 가져올 수 없습니다</p>
                    <p className="text-xs mt-1">{containerLogs.error}</p>
                  </div>
                ) : containerLogs?.logs?.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Terminal className="w-8 h-8 mx-auto mb-2" />
                    <p>최근 1시간 내 로그가 없습니다</p>
                  </div>
                ) : (
                  <div className="space-y-1">
                    {containerLogs?.logs?.map((log: any, index: number) => (
                      <div
                        key={index}
                        className="flex gap-3 hover:bg-white/5 px-2 py-0.5 rounded"
                      >
                        <span className="text-muted-foreground shrink-0 text-xs">
                          {log.timestamp}
                        </span>
                        <span className={cn(
                          "break-all",
                          log.message.toLowerCase().includes('error') && "text-profit-negative",
                          log.message.toLowerCase().includes('warn') && "text-jennie-gold",
                          log.message.toLowerCase().includes('success') && "text-profit-positive",
                        )}>
                          {log.message}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Modal Footer */}
              <div className="p-3 border-t border-white/10 bg-white/5 flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {containerLogs?.count || 0}개 로그 (최근 1시간)
                </span>
                <span>
                  Powered by Loki + Grafana
                </span>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

