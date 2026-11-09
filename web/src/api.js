// 서버 주소는 docker-compose.yml의 VITE_API_BASE_URL로 들어온다. 없으면 로컬 서버 주소를 쓴다.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// 서버 상태 확인: GET /health → {"status": "ok"}
export async function checkHealth() {
  const res = await fetch(`${API_BASE_URL}/health`)
  if (!res.ok) return false
  const body = await res.json()
  return body.status === 'ok'
}
