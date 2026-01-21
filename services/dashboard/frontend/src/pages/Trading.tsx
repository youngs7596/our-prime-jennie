
import { useState } from 'react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    ArrowUpRight,
    ArrowDownRight,
    Activity,
    RefreshCw,
    Search,
    AlertCircle
} from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Badge } from '@/components/ui/Badge'
import { portfolioApi, tradesApi } from '@/lib/api'
import { formatCurrency, formatNumber, formatRelativeTime } from '@/lib/utils'

const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
        opacity: 1,
        transition: { staggerChildren: 0.1 },
    },
}

export function TradingPage() {
    const queryClient = useQueryClient()
    const [orderForm, setOrderForm] = useState({
        stock_code: '',
        quantity: 1,
        price: 0,
        side: 'BUY',
        order_type: 'LIMIT'
    })

    const [successMsg, setSuccessMsg] = useState('')
    const [errorMsg, setErrorMsg] = useState('')

    const { data: recentTrades } = useQuery({
        queryKey: ['recent-trades'],
        queryFn: () => tradesApi.getRecent(20),
        refetchInterval: 10000,
    })

    const orderMutation = useMutation({
        mutationFn: portfolioApi.createOrder,
        onSuccess: (data) => {
            setSuccessMsg(`주문 성공: ${data.message}`)
            setErrorMsg('')
            setOrderForm(prev => ({ ...prev, stock_code: '', quantity: 1, price: 0 }))
            queryClient.invalidateQueries(['recent-trades'])
            setTimeout(() => setSuccessMsg(''), 5000)
        },
        onError: (error: any) => {
            setErrorMsg(`주문 실패: ${error.message || '알 수 없는 오류'}`)
            setSuccessMsg('')
        }
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
        <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="space-y-6"
        >
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-display font-bold">Trading</h1>
                    <p className="text-muted-foreground mt-1">수동 주문 실행 및 체결 내역 확인</p>
                </div>
            </div>

            <div className="grid gap-6 md:grid-cols-12">
                {/* 주문 폼 */}
                <Card className="md:col-span-4 h-fit">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <Activity className="w-5 h-5 text-raydium-purple" />
                            주문 하기
                        </CardTitle>
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
                                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                                        value={orderForm.order_type}
                                        onChange={(e) => setOrderForm({ ...orderForm, order_type: e.target.value })}
                                    >
                                        <option value="LIMIT">지정가 (Limit)</option>
                                        <option value="MARKET">시장가 (Market)</option>
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <Label>매매 구분</Label>
                                    <div className="flex rounded-md shadow-sm">
                                        <button
                                            type="button"
                                            onClick={() => setOrderForm({ ...orderForm, side: 'BUY' })}
                                            className={`flex-1 px-3 py-2 text-sm font-medium rounded-l-md border ${orderForm.side === 'BUY'
                                                    ? 'bg-profit-positive/20 text-profit-positive border-profit-positive'
                                                    : 'bg-background text-muted-foreground border-input hover:bg-accent'
                                                }`}
                                        >
                                            매수
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setOrderForm({ ...orderForm, side: 'SELL' })}
                                            className={`flex-1 px-3 py-2 text-sm font-medium rounded-r-md border-t border-r border-b ${orderForm.side === 'SELL'
                                                    ? 'bg-profit-negative/20 text-profit-negative border-profit-negative'
                                                    : 'bg-background text-muted-foreground border-input hover:bg-accent'
                                                }`}
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
                                <div className="text-sm text-profit-positive flex items-center gap-2 bg-profit-positive/10 p-3 rounded-md">
                                    <RefreshCw className="w-4 h-4" /> {successMsg}
                                </div>
                            )}
                            {errorMsg && (
                                <div className="text-sm text-profit-negative flex items-center gap-2 bg-profit-negative/10 p-3 rounded-md">
                                    <AlertCircle className="w-4 h-4" /> {errorMsg}
                                </div>
                            )}

                            <Button
                                type="submit"
                                className={`w-full ${orderForm.side === 'BUY'
                                        ? 'bg-profit-positive hover:bg-profit-positive/90'
                                        : 'bg-profit-negative hover:bg-profit-negative/90'
                                    }`}
                                disabled={orderMutation.isLoading}
                            >
                                {orderMutation.isLoading ? '처리중...' : `${orderForm.side === 'BUY' ? '매수' : '매도'} 주문 실행`}
                            </Button>
                        </form>
                    </CardContent>
                </Card>

                {/* 최근 체결 내역 */}
                <Card className="md:col-span-8">
                    <CardHeader>
                        <CardTitle>최근 매매 활동</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="space-y-4">
                            {recentTrades && recentTrades.length > 0 ? (
                                recentTrades.map((trade: any) => (
                                    <div
                                        key={trade.trade_id}
                                        className="flex justify-between items-center p-4 border rounded-lg bg-card/50 hover:bg-accent/50 transition-colors"
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className={`p-2 rounded-full ${trade.side === 'BUY' ? 'bg-profit-positive/10 text-profit-positive' : 'bg-profit-negative/10 text-profit-negative'
                                                }`}>
                                                {trade.side === 'BUY' ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                                            </div>
                                            <div>
                                                <p className="font-medium">{trade.stock_name} ({trade.stock_code})</p>
                                                <p className="text-xs text-muted-foreground">{formatRelativeTime(trade.executed_at)}</p>
                                            </div>
                                        </div>
                                        <div className="text-right">
                                            <p className="font-medium">{formatCurrency(trade.price)}</p>
                                            <p className="text-xs text-muted-foreground">{trade.quantity}주</p>
                                        </div>
                                    </div>
                                ))
                            ) : (
                                <div className="text-center py-8 text-muted-foreground">
                                    최근 매매 내역이 없습니다.
                                </div>
                            )}
                        </div>
                    </CardContent>
                </Card>
            </div>
        </motion.div>
    )
}
