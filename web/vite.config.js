import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 서버 CORS가 localhost:3000만 허용하므로 Docker 없이 켤 때도 3000번을 쓴다.
  // 3000번이 이미 쓰이면 다른 번호로 몰래 바꾸지 않고 멈춘다 (바뀌면 CORS로 서버 연결이 안 된다)
  server: { port: 3000, strictPort: true },
})
