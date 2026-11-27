// '나는 누구' 고르기: 이름 찾기 · 저장소가 없거나 지워진 구성원이면 다시 묻기
import assert from 'node:assert/strict'
import test from 'node:test'
import { findMember, getMe } from './hooks.js'

const members = [{ id: 1, name: '민수' }, { id: 3, name: '지영' }]

test('이름으로 구성원 찾기', () => {
  assert.equal(findMember(members, ' 지영 ').id, 3)
  assert.equal(findMember(members, '지'), null) // 일부만 맞으면 안 됨
})

test('저장된 값이 없거나 이 정산방 구성원이 아니면 null', () => {
  const store = {}
  globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v } }
  assert.equal(getMe('t1', members), null)
  store['gachi-me:t1'] = '3'
  assert.equal(getMe('t1', members), 3)
  store['gachi-me:t1'] = '2' // 지워진 구성원
  assert.equal(getMe('t1', members), null)
  globalThis.localStorage = { getItem: () => { throw new Error('blocked') } }
  assert.equal(getMe('t1', members), null)
  delete globalThis.localStorage
})
