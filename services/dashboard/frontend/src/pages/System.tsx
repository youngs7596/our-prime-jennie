import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Server,
  Database,
  MessageSquare,
  CheckCircle,
  XCircle,
  AlertCircle,
  RefreshCw,
  Container,
  Activity,
  X,
  Terminal,
  Settings,
  Play,
  RotateCw,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { systemApi, configApi } from '@/lib/api'
import { formatRelativeTime, cn } from '@/lib/utils'
import { toast } from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'

type Tab = 'infrastructure' | 'workflows' | 'logs' | 'operations'

const SERVICES = [
  'scout-job',
  'scout-worker',
  'buy-scanner',
  'buy-executor',
  'sell-executor',
  'price-monitor',
  'kis-gateway',
  'news-collector',
  'news-analyzer',
  'news-archiver',
  'dashboard-backend',
]

const getStatusIcon = (status: string) => {
  switch (status.toLowerCase()) {
    case 'active':
    case 'running':
    case 'up':
    case 'healthy':
      return <CheckCircle className="w-4 h-4 text-green-500" />
    case 'inactive':
    case 'stopped':
    case 'down':
      return <XCircle className="w-4 h-4 text-muted-foreground" />
    case 'error':
    case 'unhealthy':
      return <AlertCircle className="w-4 h-4 text-red-500" />
    default:
      return <Activity className="w-4 h-4 text-yellow-500" />
  }
}

export function SystemPage() {
  const [activeTab, setActiveTab] = useState<Tab>('infrastructure')

  return (
    <div className="space-y-6">
      {/* Header with tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">System</h1>
          <p className="text-sm text-muted-foreground mt-1">
            인프라, 워크플로우 및 로그 모니터링
          </p>
        </div>
        <div className="flex gap-1 p-1 bg-white/5 rounded-lg">
          {(['infrastructure', 'workflows', 'logs', 'operations'] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                'px-3 py-2 text-sm font-medium rounded-md transition-colors capitalize',
                activeTab === tab
                  ? 'bg-white text-black'
                  : 'text-muted-foreground hover:text-white'
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'infrastructure' && <InfrastructureTab />}
      {activeTab === 'workflows' && <WorkflowsTab />}
      {activeTab === 'logs' && <LogsTab />}
      {activeTab === 'operations' && <OperationsTab />}
    </div>
  )
}

function InfrastructureTab() {
  const [selectedContainer, setSelectedContainer] = useState<string | null>(null)

  const { data: dockerStatus, isLoading: dockerLoading, refetch: refetchDocker } = useQuery({
    queryKey: ['system-docker'],
    queryFn: systemApi.getDocker,
    refetchInterval: 5000,
  })

  const { data: rabbitmqStatus, refetch: refetchRabbitMQ } = useQuery({
    queryKey: ['system-rabbitmq'],
    queryFn: systemApi.getRabbitMQ,
    refetchInterval: 5000,
  })

  const { data: realtimeDetails, isLoading: realtimeLoading, refetch: refetchRealtime } = useQuery({
    queryKey: ['system-realtime'],
    queryFn: systemApi.getRealtimeMonitor,
    refetchInterval: 1000,
  })

  const { data: containerLogs, isLoading: logsLoading, refetch: refetchLogs } = useQuery({
    queryKey: ['container-logs', selectedContainer],
    queryFn: () => systemApi.getContainerLogs(selectedContainer!),
    enabled: !!selectedContainer,
    refetchInterval: 5000,
  })

  const handleRefreshAll = () => {
    refetchDocker()
    refetchRabbitMQ()
    refetchRealtime()
  }

  return (
    <div className="space-y-6">
      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-green-500/10">
                <Container className="w-5 h-5 text-green-500" />
              </div>
              <div>
                <p className="text-2xl font-semibold text-white">{dockerStatus?.count || 0}</p>
                <p className="text-xs text-muted-foreground">Running Containers</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10">
                <MessageSquare className="w-5 h-5 text-blue-500" />
              </div>
              <div>
                <p className="text-2xl font-semibold text-white">
                  {rabbitmqStatus?.queues?.reduce(
                    (sum: number, q: any) => sum + (q.messages || 0),
                    0
                  ) || 0}
                </p>
                <p className="text-xs text-muted-foreground">Pending Messages</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-purple-500/10">
                <Database className="w-5 h-5 text-purple-500" />
              </div>
              <div>
                <p className="text-2xl font-semibold text-white">MariaDB</p>
                <p className="text-xs text-muted-foreground">Primary DB (WSL2)</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <Button variant="outline" onClick={handleRefreshAll} className="w-full gap-2">
              <RefreshCw className="w-4 h-4" />
              Refresh All
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Real-time Watcher Status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Activity className="w-4 h-4 text-yellow-500" />
            Real-time Watcher Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {realtimeLoading ? (
            <div className="h-12 w-full bg-white/5 animate-pulse rounded" />
          ) : !realtimeDetails || realtimeDetails.status === 'offline' ? (
            <p className="text-sm text-muted-foreground text-center py-4">
              Monitoring offline - check Price Monitor
            </p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="p-3 bg-white/5 rounded-lg text-center">
                <p className="text-xs text-muted-foreground mb-1">Hot Watchlist</p>
                <p className="text-lg font-semibold text-white">
                  {realtimeDetails.metrics?.hot_watchlist_size ?? 0}
                </p>
              </div>
              <div className="p-3 bg-white/5 rounded-lg text-center">
                <p className="text-xs text-muted-foreground mb-1">Tick Count</p>
                <p className="text-lg font-semibold text-white">
                  {realtimeDetails.metrics?.tick_count ?? 0}
                </p>
              </div>
              <div className="p-3 bg-white/5 rounded-lg text-center">
                <p className="text-xs text-muted-foreground mb-1">Signals</p>
                <p className="text-lg font-semibold text-yellow-500">
                  {realtimeDetails.metrics?.signal_count ?? 0}
                </p>
              </div>
              <div className="p-3 bg-white/5 rounded-lg text-center">
                <p className="text-xs text-muted-foreground mb-1">Market Regime</p>
                <p className="text-lg font-semibold text-blue-500">
                  {realtimeDetails.metrics?.market_regime ?? 'UNK'}
                </p>
              </div>
              <div className="p-3 bg-white/5 rounded-lg text-center">
                <p className="text-xs text-muted-foreground mb-1">Last Active</p>
                <p className="text-xs font-mono text-white">
                  {realtimeDetails.metrics?.updated_at
                    ? formatRelativeTime(realtimeDetails.metrics.updated_at)
                    : '-'}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Docker Containers */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Container className="w-4 h-4 text-blue-500" />
            Docker Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {dockerLoading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-12 rounded-lg bg-white/5 animate-pulse" />
              ))}
            </div>
          ) : dockerStatus?.error ? (
            <div className="text-center py-8 text-muted-foreground">
              <AlertCircle className="w-8 h-8 mx-auto mb-2 text-red-500" />
              <p>Unable to fetch Docker status</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {dockerStatus?.containers?.map((container: any) => (
                <div
                  key={container.ID}
                  onClick={() => setSelectedContainer(container.Names)}
                  className="p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors cursor-pointer group"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-sm truncate flex items-center gap-2 text-white">
                      {container.Names}
                      <Terminal className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-blue-500" />
                    </span>
                    {getStatusIcon(container.Status?.includes('Up') ? 'running' : 'stopped')}
                  </div>
                  <p className="text-xs text-muted-foreground truncate">{container.Image}</p>
                  <p className="text-xs text-muted-foreground mt-1">{container.Status}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* RabbitMQ Queues */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-blue-500" />
            RabbitMQ Queues
          </CardTitle>
        </CardHeader>
        <CardContent>
          {rabbitmqStatus?.error ? (
            <div className="text-center py-8 text-muted-foreground">
              <AlertCircle className="w-8 h-8 mx-auto mb-2 text-red-500" />
              <p>Unable to fetch RabbitMQ status</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {rabbitmqStatus?.queues?.map((queue: any) => (
                <div
                  key={queue.name}
                  className="p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm truncate text-white">{queue.name}</span>
                    <span
                      className={cn(
                        'px-2 py-0.5 rounded-full text-xs font-medium',
                        queue.messages > 0
                          ? 'bg-yellow-500/20 text-yellow-500'
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

      {/* Environment */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Server className="w-4 h-4 text-muted-foreground" />
            Environment
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-3 rounded-lg bg-white/5">
              <p className="text-xs text-muted-foreground">Platform</p>
              <p className="font-medium text-white">WSL2 (Ubuntu)</p>
            </div>
            <div className="p-3 rounded-lg bg-white/5">
              <p className="text-xs text-muted-foreground">Orchestration</p>
              <p className="font-medium text-white">Docker Compose</p>
            </div>
            <div className="p-3 rounded-lg bg-white/5">
              <p className="text-xs text-muted-foreground">Primary DB</p>
              <p className="font-medium text-white">MariaDB (WSL2)</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Log Viewer Modal */}
      {selectedContainer && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={() => setSelectedContainer(null)}
        >
          <div
            className="bg-card border border-white/10 rounded-lg w-full max-w-4xl max-h-[80vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-white/5">
              <div className="flex items-center gap-3">
                <Terminal className="w-5 h-5 text-blue-500" />
                <h3 className="font-medium text-white">{selectedContainer}</h3>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => refetchLogs()} className="gap-1">
                  <RefreshCw className={cn('w-4 h-4', logsLoading && 'animate-spin')} />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setSelectedContainer(null)}>
                  <X className="w-4 h-4" />
                </Button>
              </div>
            </div>
            <div className="p-4 overflow-auto max-h-[60vh] font-mono text-sm bg-black/50">
              {logsLoading && !containerLogs ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" />
                  Loading logs...
                </div>
              ) : containerLogs?.error ? (
                <div className="text-center py-8 text-muted-foreground">
                  <AlertCircle className="w-8 h-8 mx-auto mb-2 text-red-500" />
                  <p>Unable to fetch logs</p>
                </div>
              ) : containerLogs?.logs?.length === 0 ? (
                <p className="text-center py-8 text-muted-foreground">No recent logs</p>
              ) : (
                <div className="space-y-1">
                  {containerLogs?.logs?.map((log: any, index: number) => (
                    <div key={index} className="flex gap-3 hover:bg-white/5 px-2 py-0.5 rounded">
                      <span className="text-muted-foreground shrink-0 text-xs">{log.timestamp}</span>
                      <span
                        className={cn(
                          'break-all text-white',
                          log.message.toLowerCase().includes('error') && 'text-red-400',
                          log.message.toLowerCase().includes('warn') && 'text-yellow-400'
                        )}
                      >
                        {log.message}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function WorkflowsTab() {
  const [dags, setDags] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [triggerLoading, setTriggerLoading] = useState<string | null>(null)
  const { token } = useAuthStore()

  useEffect(() => {
    fetchDags()
  }, [])

  const fetchDags = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/airflow/dags', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setDags(data)
      }
    } catch (error) {
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  const handleTrigger = async (dagId: string) => {
    setTriggerLoading(dagId)
    try {
      const res = await fetch(`/api/airflow/dags/${dagId}/trigger`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        toast.success(`Triggered ${dagId}`)
        setTimeout(fetchDags, 2000)
      } else {
        toast.error('Failed to trigger')
      }
    } catch (error) {
      console.error(error)
    } finally {
      setTriggerLoading(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={fetchDags} className="gap-2">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {loading && dags.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">Loading workflows...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {dags.map((dag) => (
            <Card key={dag.dag_id}>
              <CardContent className="p-5">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <h3 className="font-medium text-white">{dag.dag_id}</h3>
                    <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                      {dag.description || 'No description'}
                    </p>
                  </div>
                  <span
                    className={cn(
                      'px-2 py-1 rounded text-xs font-medium',
                      dag.last_run_state === 'success' && 'bg-green-500/10 text-green-500',
                      dag.last_run_state === 'running' && 'bg-blue-500/10 text-blue-500',
                      dag.last_run_state === 'failed' && 'bg-red-500/10 text-red-500',
                      !dag.last_run_state && 'bg-white/10 text-muted-foreground'
                    )}
                  >
                    {dag.last_run_state || 'READY'}
                  </span>
                </div>

                <div className="space-y-2 text-sm text-muted-foreground mb-4">
                  <div className="flex justify-between">
                    <span>Schedule:</span>
                    <span className="font-mono bg-white/5 px-1 rounded">
                      {typeof dag.schedule_interval === 'object' && dag.schedule_interval !== null
                        ? dag.schedule_interval.value || JSON.stringify(dag.schedule_interval)
                        : dag.schedule_interval || 'Manual'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Last Run:</span>
                    <span>
                      {dag.last_run_date ? new Date(dag.last_run_date).toLocaleString() : '-'}
                    </span>
                  </div>
                </div>

                <Button
                  variant="secondary"
                  size="sm"
                  className="w-full gap-2"
                  onClick={() => handleTrigger(dag.dag_id)}
                  disabled={triggerLoading === dag.dag_id}
                >
                  {triggerLoading === dag.dag_id ? (
                    <RotateCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4" />
                  )}
                  Trigger Now
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function LogsTab() {
  const [logs, setLogs] = useState<any[]>([])
  const [selectedService, setSelectedService] = useState('scout-job')
  const [timeRange, setTimeRange] = useState('1h')
  const [loading, setLoading] = useState(false)
  const { token } = useAuthStore()

  useEffect(() => {
    fetchLogs()
  }, [selectedService, timeRange])

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const now = Date.now()
      let start = now - 60 * 60 * 1000
      if (timeRange === '5m') start = now - 5 * 60 * 1000
      if (timeRange === '30m') start = now - 30 * 60 * 1000
      if (timeRange === '6h') start = now - 6 * 60 * 60 * 1000

      const startNs = start * 1000000

      const res = await fetch(
        `/api/logs/stream?service=${selectedService}&limit=1000&start=${startNs}`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (res.ok) {
        const data = await res.json()
        setLogs(data.logs || [])
      }
    } catch (error) {
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-4">
        <select
          value={selectedService}
          onChange={(e) => setSelectedService(e.target.value)}
          className="bg-white/5 border border-white/10 text-white text-sm rounded-md px-3 py-2"
        >
          {SERVICES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <div className="flex gap-1 p-1 bg-white/5 rounded-md">
          {['5m', '30m', '1h', '6h'].map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={cn(
                'px-3 py-1 text-xs font-medium rounded transition-colors',
                timeRange === range ? 'bg-white text-black' : 'text-muted-foreground hover:text-white'
              )}
            >
              {range}
            </button>
          ))}
        </div>

        <Button variant="ghost" size="sm" onClick={fetchLogs}>
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </Button>
      </div>

      {/* Log viewer */}
      <Card className="bg-black border-white/10">
        <CardContent className="p-0">
          <div className="p-3 border-b border-white/5 flex items-center gap-2 text-muted-foreground">
            <Terminal className="w-4 h-4" />
            <span className="font-mono text-sm">/var/log/{selectedService}.log</span>
          </div>
          <div className="h-[500px] overflow-auto p-4 font-mono text-xs">
            {logs.length === 0 ? (
              <p className="text-muted-foreground">No logs found...</p>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="mb-1 flex gap-3 hover:bg-white/5 px-1 rounded">
                  <span className="text-muted-foreground shrink-0">
                    {new Date(log.timestamp / 1000000).toLocaleTimeString('ko-KR')}
                  </span>
                  <span
                    className={cn(
                      'break-all whitespace-pre-wrap text-white/80',
                      log.message.toLowerCase().includes('error') && 'text-red-400',
                      log.message.toLowerCase().includes('warn') && 'text-yellow-400'
                    )}
                  >
                    {log.message}
                  </span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function OperationsTab() {
  const queryClient = useQueryClient()

  const { data: configData } = useQuery({
    queryKey: ['config-list'],
    queryFn: configApi.list,
    refetchInterval: 60000,
  })

  const updateConfigMutation = useMutation({
    mutationFn: ({ key, value }: { key: string; value: boolean }) => configApi.update(key, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config-list'] })
      toast.success('Setting saved')
    },
    onError: (error) => {
      toast.error('Failed to save: ' + (error as Error).message)
    },
  })

  const disableMarketCheck = Array.isArray(configData)
    ? configData.find((c: { key: string; value: boolean }) => c.key === 'DISABLE_MARKET_OPEN_CHECK')
        ?.value ?? false
    : false

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Settings className="w-4 h-4 text-yellow-500" />
            Runtime Settings
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Market check toggle */}
          <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 hover:bg-white/[0.07] transition-colors">
            <div>
              <h4 className="font-medium text-sm text-white">Disable Market Hours Check</h4>
              <p className="text-xs text-muted-foreground mt-1">
                Enable to run services outside market hours (09:00~15:30)
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
                disableMarketCheck ? 'bg-blue-500' : 'bg-white/20',
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

          <div className="text-xs text-muted-foreground text-center">
            Current:{' '}
            {disableMarketCheck ? (
              <span className="text-yellow-500 font-medium">Test Mode (24h)</span>
            ) : (
              <span className="text-green-500 font-medium">Production (Market Hours Only)</span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default SystemPage
