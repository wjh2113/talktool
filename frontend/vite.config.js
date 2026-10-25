import { defineConfig, loadEnv } from 'vite'
import { readFileSync } from 'node:fs'
import uni from '@dcloudio/vite-plugin-uni'

// H5 开发时把 /api 与 /media 代理到后端，前后端同源，手机走 HTTPS 隧道时也只需暴露一个地址
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [{
      name: 'talktool-notification-assets',
      configureServer(server) {
        // uni 的开发中间件会把 .js 当成模块转换；通知脚本必须原样提供。
        const types = { '/sw.js': 'application/javascript', '/manifest.webmanifest': 'application/manifest+json', '/pwa-icon.svg': 'image/svg+xml' }
        server.middlewares.use((req, res, next) => {
          const path = (req.url || '').split('?')[0]
          if (!types[path]) return next()
          res.setHeader('Content-Type', types[path])
          res.setHeader('Cache-Control', 'no-cache')
          res.end(readFileSync(new URL('./public' + path, import.meta.url)))
        })
      }
    }, uni()],
    publicDir: new URL('./public', import.meta.url).pathname,
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: true },
        '/media': { target, changeOrigin: true }
      }
    }
  }
})
