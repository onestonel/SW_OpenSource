import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 서버 CORS가 localhost:3000만 허용하므로 Docker 없이 켤 때도 3000번을 쓴다
  server: { port: 3000 },
})
