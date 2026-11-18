// 목 서버 확인: node --test (V1 요구 명세 예시 1 · 최신 아님 · 검사 오류)
import assert from 'node:assert/strict'
import test from 'node:test'
import { mockRequest as req } from './mock.js'

test('예시 1: B → A 145,000 / C → A 145,000 / D → A 115,000', async () => {
  const room = await req('POST', '/rooms', { name: '제주 여행', members: ['A', 'B', 'C', 'D'] })
  const t = `/rooms/${room.room_token}`
  const [a] = room.members

  const air = await req('POST', `${t}/receipts`, {
    store_name: '항공권', payer_member_id: a.id, total_amount: 400000,
    items: [{ name: '항공권', amount: 400000, kind: 'ITEM' }],
  })
  const food = await req('POST', `${t}/receipts`, {
    store_name: '식당', payer_member_id: a.id, total_amount: 150000,
    items: [
      { name: '김치찌개', amount: 10000, kind: 'ITEM' },
      { name: '고기', amount: 50000, kind: 'ITEM' },
      { name: '술', amount: 90000, kind: 'ITEM' },
    ],
  })
  await req('POST', `${t}/receipts/${air.id}/confirm`)
  await req('POST', `${t}/receipts/${food.id}/confirm`)

  const drink = food.items[2]
  await req('PUT', `${t}/checks`, { items: [{ item_id: drink.id, member_ids: room.members.slice(0, 3).map((m) => m.id) }] })

  const s = await req('POST', `${t}/settlements`)
  assert.deepEqual(s.transfers.map((x) => `${x.from.name}>${x.to.name} ${x.amount}`), ['B>A 145000', 'C>A 145000', 'D>A 115000'])
  assert.equal(s.version, 1)
  assert.equal((await req('GET', `${t}/settlements/latest`)).is_stale, false)

  await req('PATCH', t, { rounding: 'WON_10' })
  assert.equal((await req('GET', `${t}/settlements/latest`)).is_stale, true)
})

test('검사: 구성원 2명 미만 · 확정 영수증 고치기', async () => {
  // 진짜 서버와 같은 모양: message는 공통 문구, 이유는 fields에
  await assert.rejects(req('POST', '/rooms', { name: 'x', members: ['A'] }), { status: 422, fields: { members: '2개 이상이어야 합니다' } })
  await assert.rejects(req('POST', '/rooms', { name: ' ', members: ['A', ''] }), { fields: { name: '빈 값은 안 됩니다', 'members.1': '빈 값은 안 됩니다' } })
  await assert.rejects(req('POST', '/rooms', { name: 'x', members: ['A', 'B', 'A'] }), { status: 409, code: 'MEMBER_NAME_DUPLICATE', message: '같은 이름의 구성원이 있습니다: A' })

  const room = await req('POST', '/rooms', { name: 'x', members: ['A', 'B'] })
  const t = `/rooms/${room.room_token}`
  const body = { store_name: '카페', payer_member_id: room.members[0].id, total_amount: 9000, items: [{ name: '커피', amount: 9000, kind: 'ITEM' }] }
  const rc = await req('POST', `${t}/receipts`, body)
  await req('POST', `${t}/receipts/${rc.id}/confirm`)
  await assert.rejects(req('PUT', `${t}/receipts/${rc.id}`, body), { status: 409, code: 'RECEIPT_CONFIRMED' })
})

test('말로 바꾸기: 빼기 · 다 내기 · 다시 묻기 (저장하지 않음)', async () => {
  const room = await req('POST', '/rooms', { name: '회식', members: ['민수', '지영', '현우', '수아'] })
  const t = `/rooms/${room.room_token}`
  const [a, b, c] = room.members.map((m) => m.id)
  await assert.rejects(req('POST', `${t}/checks/interpret`, { text: '수아는 소주 안 마셨어' }), { status: 409 })

  const rc = await req('POST', `${t}/receipts`, {
    store_name: '1차', payer_member_id: a, total_amount: 120000,
    items: [{ name: '삼겹살', amount: 80000, kind: 'ITEM' }, { name: '소주', amount: 40000, kind: 'ITEM' }],
  })
  await req('POST', `${t}/receipts/${rc.id}/confirm`)

  const ex = await req('POST', `${t}/checks/interpret`, { text: '수아는 소주 안 마셨어' })
  assert.equal(ex.status, 'PARSED')
  assert.deepEqual(ex.changes[0].after_member_ids, [a, b, c])
  const checks = await req('GET', `${t}/checks`)
  assert.equal(checks.items[1].member_ids.length, 4) // 저장은 하지 않는다

  const full = await req('POST', `${t}/checks/interpret`, { text: '소주는 지영이가 다 낼게' })
  assert.deepEqual([full.changes[0].rule, full.changes[0].after_member_ids], ['FULL', [b]])

  assert.equal((await req('POST', `${t}/checks/interpret`, { text: '오늘 재밌었다' })).status, 'NEEDS_CLARIFICATION')
})
