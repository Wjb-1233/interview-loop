import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/** simli-client 及其唯一传递依赖 livekit-client 的整棵依赖树：只有 SimliPresenter 动态用到，
 *  单独成 chunk 后不再挂在入口上（入口因此回落约 600 kB）。 */
const SIMLI_MODULES = /node_modules[\\/](?:simli-client|livekit-client|@livekit|jose|sdp-transform|webrtc-adapter|machina|typed-emitter|events|loglevel)[\\/]/

export default defineConfig({
  plugins: [
    vue(),
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (SIMLI_MODULES.test(id)) return 'vendor-simli'
          if (id.includes('markdown-it') || id.includes('dompurify')) return 'vendor-markdown'
          if (id.includes('reka-ui') || id.includes('lucide')) return 'vendor-ui'
          if (id.includes('axios')) return 'vendor-http'
          if (id.includes('vue') || id.includes('@vue')) return 'vendor-vue'
          return undefined
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      // 默认连本机 8081；需要预览另一套后端时用 API_TARGET 覆盖
      '/api': { target: process.env.API_TARGET || 'http://127.0.0.1:8081', ws: true },
      '/media': process.env.API_TARGET || 'http://127.0.0.1:8081',
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8081', ws: true },
      '/media': 'http://127.0.0.1:8081',
    },
  },
})

