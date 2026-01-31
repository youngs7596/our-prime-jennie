import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000, // 1분 - 데이터가 "신선"한 것으로 간주되는 시간
      gcTime: 10 * 60 * 1000, // 10분 - 캐시에 유지되는 시간 (구 cacheTime)
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: 1, // 재시도 횟수 줄임
      retryDelay: 1000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
