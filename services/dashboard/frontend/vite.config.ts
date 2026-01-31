import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8090',
        ws: true,
      },
    },
  },
  build: {
    // 청크 크기 경고 임계값 (500KB)
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // 수동 청크 분리 - 대형 라이브러리 분리
        manualChunks: {
          // React 코어
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // 차트 라이브러리 (가장 큰 청크)
          'vendor-charts': ['recharts', 'lightweight-charts'],
          // UI 컴포넌트 라이브러리
          'vendor-radix': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-select',
            '@radix-ui/react-tabs',
            '@radix-ui/react-tooltip',
            '@radix-ui/react-toast',
            '@radix-ui/react-scroll-area',
            '@radix-ui/react-progress',
            '@radix-ui/react-separator',
            '@radix-ui/react-avatar',
            '@radix-ui/react-label',
            '@radix-ui/react-slot',
          ],
          // 애니메이션 라이브러리
          'vendor-motion': ['framer-motion'],
          // 상태 관리 & 데이터 페칭
          'vendor-state': ['zustand', '@tanstack/react-query', 'axios'],
        },
      },
    },
    // 소스맵 비활성화 (프로덕션)
    sourcemap: false,
    // CSS 코드 분리
    cssCodeSplit: true,
    // minify 설정
    minify: 'esbuild',
    target: 'es2020',
  },
})

