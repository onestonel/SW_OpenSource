// 서버 상태 확인: 서버만 켜지고 DB가 꺼진 경우(503)를 따로 구분하는지 (api-v1.md 1절)
import assert from 'node:assert/strict'
import test from 'node:test'
import { checkHealth } from './api.js'

const reply = (status, body) => () => Promise.resolve(new Response(JSON.stringify(body), { status }))

test('health: 정상 · DB만 꺼짐 · 서버 꺼짐', async () => {
  globalThis.fetch = reply(200, { status: 'ok', db: 'ok' })
  assert.equal(await checkHealth(), 'ok')

  globalThis.fetch = reply(503, { status: 'error', db: 'error' })
  assert.equal(await checkHealth(), 'db')

  globalThis.fetch = reply(500, { error: { code: 'INTERNAL_ERROR' } })
  assert.equal(await checkHealth(), 'fail')

  globalThis.fetch = () => Promise.reject(new TypeError('Failed to fetch'))
  assert.equal(await checkHealth(), 'fail')
})
