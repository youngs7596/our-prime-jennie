import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Search,
  ArrowUpDown,
  ExternalLink,
  BarChart2,
  X,
  ArrowUpRight,
  ArrowDownRight,
  AlertCircle,
  RefreshCw,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Label } from '@/components/ui/Label'
import { portfolioApi, tradesApi } from '@/lib/api'
import { formatCurrency, formatPercent, formatNumber, getProfitColor, formatRelativeTime, cn } from '@/lib/utils'
import TradingChart from '@/components/TradingChart'

type Tab = 'positions' | 'trading'

export function PortfolioPage() {
  const [activeTab, setActiveTab] = useState<Tab>('positions')

  return (
    <div className="space-y-6">
      {/* Header with tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Portfolio</h1>
          <p className="text-sm text-muted-foreground mt-1">
            보유 종목 및 매매 관리
          </p>
        </div>
        <div className="flex gap-1 p-1 bg-white/5 rounded-lg">
          <button
            onClick={() => setActiveTab('positions')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'positions'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            Positions
          </button>
          <button
            onClick={() => setActiveTab('trading')}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-colors',
              activeTab === 'trading'
                ? 'bg-white text-black'
                : 'text-muted-foreground hover:text-white'
            )}
          >
            Trading
          </button>
        </div>
      </div>

      {activeTab === 'positions' ? <PositionsTab /> : <TradingTab />}
    </div>
  )
}

function PositionsTab() {
  const [searchTerm, setSearchTerm] = useState('')
  const [sortBy, setSortBy] = useState<'profit' | 'weight' | 'name'>('weight')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [selectedStock, setSelectedStock] = useState<{ code: string; name: string } | null>(null)

  const { data: positions, isLoading } = useQuery({
    queryKey: ['portfolio-positions'],
    queryFn: portfolioApi.getPositions,
    refetchInterval: 60000, // 1분 (30초 → 1분)
    staleTime: 30000,
  })

  const { data: summary } = useQuery({
    queryKey: ['portfolio-summary'],
    queryFn: portfolioApi.getSummary,
  })

  const filteredPositions = positions
    ?.filter(
      (p: any) =>
        p.stock_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.stock_code.includes(searchTerm)
    )
    .sort((a: any, b: any) => {
      let comparison = 0
      if (sortBy === 'profit') {
        comparison = a.profit_rate - b.profit_rate
      } else if (sortBy === 'weight') {
        comparison = a.weight - b.weight
      } else {
        comparison = a.stock_name.localeCompare(b.stock_name)
      }
      return sortOrder === 'desc' ? -comparison : comparison
    })

  const toggleSort = (field: 'profit' | 'weight' | 'name') => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(field)
      setSortOrder('desc')
    }
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">총 평가금액</p>
            <p className="text-2xl font-semibold text-white mt-1">
              {formatCurrency((summary?.total_value || 0) - (summary?.cash_balance || 0))}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">총 투자금액</p>
            <p className="text-2xl font-semibold text-white mt-1">
              {formatCurrency(summary?.total_invested || 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">총 수익</p>
            <p className={cn('text-2xl font-semibold mt-1', getProfitColor(summary?.total_profit || 0))}>
              {formatCurrency(summary?.total_profit || 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">수익률</p>
            <p className={cn('text-2xl font-semibold mt-1', getProfitColor(summary?.profit_rate || 0))}>
              {formatPercent(summary?.profit_rate || 0)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Chart Modal */}
      {selectedStock && (
        <div className="relative">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedStock(null)}
            className="absolute -top-2 right-0 z-10"
          >
            <X className="w-4 h-4" />
          </Button>
          <TradingChart stockCode={selectedStock.code} stockName={selectedStock.name} height={350} />
        </div>
      )}

      {/* Search & Sort */}
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="종목명 또는 코드로 검색..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-10"
          />
        </div>
        <div className="flex gap-2">
          <Button
            variant={sortBy === 'weight' ? 'default' : 'outline'}
            size="sm"
            onClick={() => toggleSort('weight')}
            className="gap-1"
          >
            비중
            <ArrowUpDown className="w-3 h-3" />
          </Button>
          <Button
            variant={sortBy === 'profit' ? 'default' : 'outline'}
            size="sm"
            onClick={() => toggleSort('profit')}
            className="gap-1"
          >
            수익률
            <ArrowUpDown className="w-3 h-3" />
          </Button>
          <Button
            variant={sortBy === 'name' ? 'default' : 'outline'}
            size="sm"
            onClick={() => toggleSort('name')}
            className="gap-1"
          >
            이름
            <ArrowUpDown className="w-3 h-3" />
          </Button>
        </div>
      </div>

      {/* Positions List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            보유 종목 ({filteredPositions?.length || 0}개)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-20 rounded-lg bg-white/5 animate-pulse" />
              ))}
            </div>
          ) : filteredPositions?.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {searchTerm ? '검색 결과가 없습니다' : '보유 종목이 없습니다'}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredPositions?.map((position: any) => (
                <div
                  key={position.stock_code}
                  className="group p-4 rounded-lg bg-white/5 hover:bg-white/[0.07] border border-transparent hover:border-white/10 transition-all"
                >
                  <div className="flex items-center justify-between">
                    {/* Stock Info */}
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center">
                        <span className="font-semibold text-white">{position.stock_name[0]}</span>
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-white">{position.stock_name}</h3>
                          <span className="text-xs text-muted-foreground font-mono">
                            {position.stock_code}
                          </span>
                          <button
                            onClick={() =>
                              setSelectedStock({ code: position.stock_code, name: position.stock_name })
                            }
                            className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-white/10 rounded"
                          >
                            <BarChart2 className="w-3 h-3 text-muted-foreground" />
                          </button>
                          <a
                            href={`https://finance.naver.com/item/main.naver?code=${position.stock_code}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <ExternalLink className="w-3 h-3 text-muted-foreground hover:text-white" />
                          </a>
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {formatNumber(position.quantity)}주 × {formatNumber(position.avg_price)}원
                        </p>
                      </div>
                    </div>

                    {/* Current Price */}
                    <div className="text-center">
                      <p className="text-sm text-muted-foreground">현재가</p>
                      <p className="font-mono font-medium text-white">
                        {formatNumber(position.current_price)}원
                      </p>
                    </div>

                    {/* Profit */}
                    <div className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        {position.profit >= 0 ? (
                          <TrendingUp className="w-4 h-4 text-green-500" />
                        ) : (
                          <TrendingDown className="w-4 h-4 text-red-500" />
                        )}
                        <span className={cn('font-mono font-medium', getProfitColor(position.profit))}>
                          {formatCurrency(position.profit)}
                        </span>
                      </div>
                      <p className={cn('text-sm font-medium', getProfitColor(position.profit_rate))}>
                        {formatPercent(position.profit_rate)}
                      </p>
                    </div>

                    {/* Weight */}
                    <div className="w-24">
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="text-muted-foreground">비중</span>
                        <span className="font-medium text-white">{position.weight.toFixed(1)}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${position.weight}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function TradingTab() {
  const queryClient = useQueryClient()
  const [orderForm, setOrderForm] = useState({
    stock_code: '',
    quantity: 1,
    price: 0,
    side: 'BUY',
    order_type: 'LIMIT',
  })
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  const { data: recentTrades } = useQuery({
    queryKey: ['recent-trades'],
    queryFn: () => tradesApi.getRecent(20),
    refetchInterval: 30000, // 30초 (10초 → 30초)
    staleTime: 15000,
  })

  const orderMutation = useMutation({
    mutationFn: portfolioApi.createOrder,
    onSuccess: (data) => {
      setSuccessMsg(`주문 성공: ${data.message}`)
      setErrorMsg('')
      setOrderForm((prev) => ({ ...prev, stock_code: '', quantity: 1, price: 0 }))
      queryClient.invalidateQueries({ queryKey: ['recent-trades'] })
      setTimeout(() => setSuccessMsg(''), 5000)
    },
    onError: (error: any) => {
      setErrorMsg(`주문 실패: ${error.message || '알 수 없는 오류'}`)
      setSuccessMsg('')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!orderForm.stock_code) {
      setErrorMsg('종목 코드를 입력해주세요')
      return
    }
    orderMutation.mutate(orderForm)
  }

  return (
    <div className="grid gap-6 md:grid-cols-12">
      {/* Order Form */}
      <Card className="md:col-span-4 h-fit">
        <CardHeader>
          <CardTitle className="text-sm font-medium">주문 하기</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label>종목 코드</Label>
              <div className="relative">
                <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="005930"
                  className="pl-9"
                  value={orderForm.stock_code}
                  onChange={(e) => setOrderForm({ ...orderForm, stock_code: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>주문 유형</Label>
                <select
                  className="flex h-9 w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm"
                  value={orderForm.order_type}
                  onChange={(e) => setOrderForm({ ...orderForm, order_type: e.target.value })}
                >
                  <option value="LIMIT">지정가</option>
                  <option value="MARKET">시장가</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label>매매 구분</Label>
                <div className="flex rounded-md">
                  <button
                    type="button"
                    onClick={() => setOrderForm({ ...orderForm, side: 'BUY' })}
                    className={cn(
                      'flex-1 px-3 py-2 text-sm font-medium rounded-l-md border transition-colors',
                      orderForm.side === 'BUY'
                        ? 'bg-green-500/20 text-green-500 border-green-500/50'
                        : 'bg-white/5 text-muted-foreground border-white/10'
                    )}
                  >
                    매수
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrderForm({ ...orderForm, side: 'SELL' })}
                    className={cn(
                      'flex-1 px-3 py-2 text-sm font-medium rounded-r-md border-t border-r border-b transition-colors',
                      orderForm.side === 'SELL'
                        ? 'bg-red-500/20 text-red-500 border-red-500/50'
                        : 'bg-white/5 text-muted-foreground border-white/10'
                    )}
                  >
                    매도
                  </button>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label>수량</Label>
              <Input
                type="number"
                min="1"
                value={orderForm.quantity}
                onChange={(e) => setOrderForm({ ...orderForm, quantity: parseInt(e.target.value) || 0 })}
              />
            </div>

            {orderForm.order_type === 'LIMIT' && (
              <div className="space-y-2">
                <Label>가격 (원)</Label>
                <Input
                  type="number"
                  step="100"
                  value={orderForm.price}
                  onChange={(e) => setOrderForm({ ...orderForm, price: parseInt(e.target.value) || 0 })}
                />
              </div>
            )}

            {successMsg && (
              <div className="text-sm text-green-500 flex items-center gap-2 bg-green-500/10 p-3 rounded-md">
                <RefreshCw className="w-4 h-4" /> {successMsg}
              </div>
            )}
            {errorMsg && (
              <div className="text-sm text-red-500 flex items-center gap-2 bg-red-500/10 p-3 rounded-md">
                <AlertCircle className="w-4 h-4" /> {errorMsg}
              </div>
            )}

            <Button
              type="submit"
              className={cn(
                'w-full',
                orderForm.side === 'BUY'
                  ? 'bg-green-500 hover:bg-green-600 text-white'
                  : 'bg-red-500 hover:bg-red-600 text-white'
              )}
              disabled={orderMutation.isPending}
            >
              {orderMutation.isPending ? '처리중...' : `${orderForm.side === 'BUY' ? '매수' : '매도'} 주문`}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Recent Trades */}
      <Card className="md:col-span-8">
        <CardHeader>
          <CardTitle className="text-sm font-medium">최근 매매 활동</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {recentTrades && recentTrades.length > 0 ? (
              recentTrades.map((trade: any) => (
                <div
                  key={trade.trade_id}
                  className="flex justify-between items-center p-4 rounded-lg bg-white/5 hover:bg-white/[0.07] transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'p-2 rounded-full',
                        trade.side === 'BUY' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'
                      )}
                    >
                      {trade.side === 'BUY' ? (
                        <ArrowUpRight className="w-4 h-4" />
                      ) : (
                        <ArrowDownRight className="w-4 h-4" />
                      )}
                    </div>
                    <div>
                      <p className="font-medium text-white">
                        {trade.stock_name} ({trade.stock_code})
                      </p>
                      <p className="text-xs text-muted-foreground">{formatRelativeTime(trade.executed_at)}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-medium text-white">{formatCurrency(trade.price)}</p>
                    <p className="text-xs text-muted-foreground">{trade.quantity}주</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-8 text-muted-foreground">최근 매매 내역이 없습니다</div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default PortfolioPage
