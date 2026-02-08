import axios from 'axios'

// 프로덕션에서는 /api로, 개발에서는 환경변수 사용
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - 인증 비활성화됨 (Cloudflare Access로 외부 인증 처리)
api.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

// Response interceptor - 에러 로깅만 수행
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // 인증 관련 리다이렉트 제거됨
    console.error('API Error:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

// API 함수들
export const authApi = {
  login: async (username: string, password: string) => {
    const response = await api.post('/auth/login', { username, password })
    return response.data
  },
  me: async () => {
    const response = await api.get('/auth/me')
    return response.data
  },
  refresh: async () => {
    const response = await api.post('/auth/refresh')
    return response.data
  },
}

export const portfolioApi = {
  getSummary: async () => {
    const response = await api.get('/portfolio/summary')
    return response.data
  },
  getPositions: async () => {
    const response = await api.get('/portfolio/positions')
    return response.data
  },
  getHistory: async (days = 30) => {
    const response = await api.get(`/portfolio/history?days=${days}`)
    return response.data
  },
  createOrder: async (order: {
    stock_code: string
    quantity: number
    price: number
    side: string
    order_type: string
  }) => {
    const response = await api.post('/portfolio/order', order)
    return response.data
  },
}

export const watchlistApi = {
  getAll: async (limit = 50) => {
    const response = await api.get(`/watchlist?limit=${limit}`)
    return response.data
  },
}

export const tradesApi = {
  getRecent: async (limit = 50, offset = 0) => {
    const response = await api.get(`/trades?limit=${limit}&offset=${offset}`)
    return response.data
  },
}

export const systemApi = {
  getStatus: async () => {
    const response = await api.get('/system/status')
    return response.data
  },
  getDocker: async () => {
    const response = await api.get('/system/docker')
    return response.data
  },
  getRabbitMQ: async () => {
    const response = await api.get('/system/rabbitmq')
    return response.data
  },
  getScheduler: async () => {
    const response = await api.get('/system/scheduler')
    return response.data
  },
  getContainerLogs: async (containerName: string, limit = 100, since = '1h') => {
    const response = await api.get(`/system/logs/${containerName}?limit=${limit}&since=${since}`)
    return response.data
  },
  getRealtimeMonitor: async () => {
    const response = await api.get('/system/realtime-monitor')
    return response.data
  },
}

// Scheduler Control API (스케줄러 작업 직접 제어)
export const schedulerApi = {
  getJobs: async () => {
    const response = await api.get('/scheduler/jobs')
    return response.data
  },
  runJob: async (jobId: string) => {
    const response = await api.post(`/scheduler/jobs/${jobId}/run`, { trigger_source: 'dashboard' })
    return response.data
  },
  pauseJob: async (jobId: string) => {
    const response = await api.post(`/scheduler/jobs/${jobId}/pause`)
    return response.data
  },
  resumeJob: async (jobId: string) => {
    const response = await api.post(`/scheduler/jobs/${jobId}/resume`)
    return response.data
  },
  updateJob: async (jobId: string, data: { cron_expr?: string; enabled?: boolean; description?: string }) => {
    const response = await api.put(`/scheduler/jobs/${jobId}`, data)
    return response.data
  },
}

export const scoutApi = {
  getStatus: async () => {
    const response = await api.get('/scout/status')
    return response.data
  },
  getResults: async () => {
    const response = await api.get('/scout/results')
    return response.data
  },
}

export const newsApi = {
  getSentiment: async (stockCode?: string, limit = 20) => {
    const params = new URLSearchParams()
    if (stockCode) params.append('stock_code', stockCode)
    params.append('limit', limit.toString())
    const response = await api.get(`/news/sentiment?${params}`)
    return response.data
  },
}

// NEW: Daily Briefing API
export const briefingApi = {
  getLatest: async () => {
    const response = await api.get('/briefing/latest')
    return response.data
  },
}

// NEW: Market Regime API
export const marketApi = {
  getRegime: async () => {
    const response = await api.get('/market/regime')
    return response.data
  },
}

// NEW: LLM Stats API
export const llmApi = {
  getStats: async () => {
    const response = await api.get('/llm/stats')
    return response.data
  },
  getConfig: async () => {
    const response = await api.get('/llm/config')
    return response.data
  },
}

// Config Registry API
export const configApi = {
  list: async () => {
    const response = await api.get('/config')
    return response.data
  },
  update: async (key: string, value: any, description?: string) => {
    const response = await api.put(`/config/${key}`, { value, description })
    return response.data
  },
}

// NEW: 3 Sages Council API
export const councilApi = {
  getDailyReview: async () => {
    const response = await api.get('/council/daily-review')
    return response.data
  },
}

// NEW: Macro Insight API - Council 분석 결과
export const macroApi = {
  getInsight: async (date?: string) => {
    const params = date ? `?date=${date}` : ''
    const response = await api.get(`/macro/insight${params}`)
    return response.data
  },
  getDates: async () => {
    const response = await api.get('/macro/dates')
    return response.data
  },
}

export const analystApi = {
  getPerformance: async (limit = 50, offset = 0, lookbackDays = 30) => {
    const response = await api.get(`/analyst/performance?limit=${limit}&offset=${offset}&lookback_days=${lookbackDays}`)
    return response.data
  },
}

