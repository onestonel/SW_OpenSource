import { ApiError } from './apiError.js'
import { mockRequest } from './mock.js'

export { ApiError }

// 서버 주소는 docker-compose.yml의 VITE_API_BASE_URL로 들어온다. 없으면 로컬 서버 주소를 쓴다.
// (import.meta.env는 Vite가 채운다. Node 테스트에서는 없어서 ?.로 읽는다)
export const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

// shortcut: 서버 API가 생기기 전까지 기본은 목(mock) 데이터. 서버가 준비되면 VITE_USE_MOCK=false로 켜거나 기본값을 바꾼다
const USE_MOCK = import.meta.env?.VITE_USE_MOCK !== 'false'

async function request(method, path, body) {
  if (USE_MOCK) return mockRequest(method, path, body)

  const isForm = body instanceof FormData
  let res
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body && !isForm ? { 'Content-Type': 'application/json' } : undefined,
      body: body && !isForm ? JSON.stringify(body) : body,
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '서버에 연결할 수 없어요. 잠시 뒤 다시 시도해 주세요.')
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error
    throw new ApiError(res.status, err?.code ?? 'INTERNAL_ERROR', err?.message ?? '알 수 없는 오류가 났어요.')
  }
  return data
}

// 서버 상태 확인 (목 모드에서도 진짜 서버를 확인한다). api-v1.md 1절:
// 200 {"status":"ok"} → 'ok' · 503 {"db":"error"} → 'db' (서버는 켜졌고 DB만 꺼짐) · 그 밖(연결 실패 포함) → 'fail'
export async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE_URL}/health`)
    const body = await res.json().catch(() => null)
    if (res.ok && body?.status === 'ok') return 'ok'
    return res.status === 503 && body?.db === 'error' ? 'db' : 'fail'
  } catch {
    return 'fail'
  }
}

// 주소 · 모양은 docs/api-v1.md (PR #17 초안)를 따른다
const room = (t) => `/rooms/${encodeURIComponent(t)}`

export const api = {
  createRoom: (body) => request('POST', '/rooms', body),
  getRoom: (t) => request('GET', room(t)),
  updateRoom: (t, body) => request('PATCH', room(t), body),

  listReceipts: (t) => request('GET', `${room(t)}/receipts`),
  createReceipt: (t, body) => request('POST', `${room(t)}/receipts`, body),
  getReceipt: (t, id) => request('GET', `${room(t)}/receipts/${id}`),
  updateReceipt: (t, id, body) => request('PUT', `${room(t)}/receipts/${id}`, body),
  deleteReceipt: (t, id) => request('DELETE', `${room(t)}/receipts/${id}`),
  confirmReceipt: (t, id) => request('POST', `${room(t)}/receipts/${id}/confirm`),
  unconfirmReceipt: (t, id) => request('POST', `${room(t)}/receipts/${id}/unconfirm`),
  uploadPhoto: (t, id, file) => {
    const form = new FormData()
    form.append('file', file)
    return request('POST', `${room(t)}/receipts/${id}/photo`, form)
  },

  getChecks: (t) => request('GET', `${room(t)}/checks`),
  saveChecks: (t, items) => request('PUT', `${room(t)}/checks`, { items }),

  recalculate: (t) => request('POST', `${room(t)}/settlements`),
  getLatestSettlement: (t) => request('GET', `${room(t)}/settlements/latest`),
}

// 서버가 준 사진 주소(/api/v1/...)는 서버 주소를 붙여서 쓴다. 목 모드는 blob: 주소를 그대로 준다
export const photoSrc = (url) => (url?.startsWith('/') ? new URL(url, API_BASE_URL).href : url)

// 금액은 정수 원으로 주고받고, 천 단위 콤마는 화면에서만 붙인다
export const won = (n) => n.toLocaleString('ko-KR')
