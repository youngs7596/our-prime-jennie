import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, IChartApi, CandlestickData, Time } from 'lightweight-charts'

interface TradingChartProps {
  stockCode: string
  stockName: string
  height?: number
}

const generateCandlestickData = (): CandlestickData<Time>[] => {
  const data: CandlestickData<Time>[] = []
  let basePrice = 70000
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - 90)

  for (let i = 0; i < 90; i++) {
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)

    const volatility = Math.random() * 0.04 - 0.02
    const open = basePrice * (1 + (Math.random() * 0.02 - 0.01))
    const close = open * (1 + volatility)
    const high = Math.max(open, close) * (1 + Math.random() * 0.01)
    const low = Math.min(open, close) * (1 - Math.random() * 0.01)

    data.push({
      time: date.toISOString().split('T')[0] as Time,
      open: Math.round(open),
      high: Math.round(high),
      low: Math.round(low),
      close: Math.round(close),
    })

    basePrice = close
  }

  return data
}

export function TradingChart({ stockCode, stockName, height = 400 }: TradingChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#000000' },
        textColor: '#a3a3a3',
      },
      grid: {
        vertLines: { color: '#1a1a1a' },
        horzLines: { color: '#1a1a1a' },
      },
      width: chartContainerRef.current.clientWidth,
      height: height,
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#0070F3',
          width: 1,
          style: 2,
        },
        horzLine: {
          color: '#0070F3',
          width: 1,
          style: 2,
        },
      },
      rightPriceScale: {
        borderColor: '#262626',
      },
      timeScale: {
        borderColor: '#262626',
        timeVisible: true,
      },
    })

    chartRef.current = chart

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#22C55E',
      downColor: '#EF4444',
      borderDownColor: '#EF4444',
      borderUpColor: '#22C55E',
      wickDownColor: '#EF4444',
      wickUpColor: '#22C55E',
    })

    const data = generateCandlestickData()
    candlestickSeries.setData(data)

    const volumeSeries = chart.addHistogramSeries({
      color: '#0070F3',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    })

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    })

    const volumeData = data.map((d) => ({
      time: d.time,
      value: Math.floor(Math.random() * 10000000) + 1000000,
      color: d.close >= d.open ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)',
    }))

    volumeSeries.setData(volumeData)
    chart.timeScale().fitContent()
    setIsLoading(false)

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [stockCode, height])

  return (
    <div className="bg-black rounded-lg border border-white/5 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium text-white">{stockName}</h3>
          <p className="text-xs text-muted-foreground">{stockCode}</p>
        </div>
        <div className="flex gap-1">
          {['1D', '1W', '1M', '3M'].map((period) => (
            <button
              key={period}
              className="px-3 py-1 text-xs font-medium rounded-md bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-white transition-colors"
            >
              {period}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/80 z-10">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
          </div>
        )}
        <div ref={chartContainerRef} />
      </div>

      {/* Legend */}
      <div className="px-4 py-2 border-t border-white/5 flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 bg-green-500 rounded-sm"></span>
          상승
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 bg-red-500 rounded-sm"></span>
          하락
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 bg-blue-500/40 rounded-sm"></span>
          거래량
        </span>
      </div>
    </div>
  )
}

export default TradingChart
