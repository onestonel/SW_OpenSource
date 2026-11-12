// 목(mock) 서버: docs/api-v1.md 초안의 주소 · 모양 · 오류를 흉내 낸다. 서버 API가 생기면 이 파일은 지운다.
// 데이터는 브라우저 localStorage에 둬서 새로고침해도 남는다 (Node 테스트에서는 메모리).
import { ApiError } from './apiError.js'

const KEY = 'gachi-mock-db'
const memory = {}
const storage = globalThis.localStorage ?? {
  getItem: (k) => memory[k] ?? null,
  setItem: (k, v) => { memory[k] = v },
}
const photos = {} // 사진은 용량이 커서 저장하지 않고 이번 탭에서만 보여 준다

const load = () => JSON.parse(storage.getItem(KEY) ?? '{"seq":1,"rooms":{}}')
const now = () => new Date().toISOString()
const fail = (status, code, message, fields) => { throw new ApiError(status, code, message, fields) }
const invalid = (message) => fail(422, 'VALIDATION_ERROR', message)

function newToken() {
  const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => abc[b % abc.length]).join('')
}

function roomOut(r) {
  const s = r.settlements.at(-1)
  return {
    room_token: r.room_token, name: r.name, rounding: r.rounding, members: r.members, created_at: r.created_at,
    latest_settlement: s ? { version: s.version, is_stale: r.stale } : null,
  }
}

function receiptOut(r, rc) {
  const payer = r.members.find((m) => m.id === rc.payer_member_id)
  const items_sum = rc.items.reduce((a, it) => a + it.amount, 0)
  return {
    id: rc.id, store_name: rc.store_name, payer: { id: payer.id, name: payer.name }, status: rc.status,
    total_amount: rc.total_amount,
    items: rc.items.map(({ id, name, amount, kind }) => ({ id, name, amount, kind })),
    check: { items_sum, difference: rc.total_amount - items_sum, is_matched: items_sum === rc.total_amount },
    photo_url: photos[`${r.room_token}/${rc.id}`] ?? null,
    created_at: rc.created_at,
  }
}

function checksOut(r) {
  return {
    members: r.members.map(({ id, name }) => ({ id, name })),
    items: r.receipts.filter((rc) => rc.status === 'CONFIRMED').flatMap((rc) =>
      rc.items.filter((it) => it.kind === 'ITEM').map((it) => ({
        item_id: it.id, receipt_id: rc.id, store_name: rc.store_name, name: it.name, amount: it.amount, member_ids: it.member_ids,
      }))),
  }
}

// 서버 검사 5개 (api-v1.md 3장)
function validateReceipt(r, body) {
  if (!r.members.some((m) => m.id === body.payer_member_id)) invalid('결제자를 골라주세요.')
  const items = body.items ?? []
  if (!items.some((it) => it.kind === 'ITEM')) invalid('품목을 1개 이상 입력해주세요.')
  if (items.some((it) => !it.name?.trim())) invalid('품목 이름을 입력해주세요.')
  if (items.some((it) => !Number.isInteger(it.amount) || (it.kind === 'ITEM' ? it.amount <= 0 : it.amount >= 0)))
    invalid('품목 금액은 0보다 크게, 할인은 0보다 작게 입력해주세요.')
  if (!Number.isInteger(body.total_amount) || body.total_amount <= 0) invalid('총액을 입력해주세요.')
}

// shortcut: 진짜 정산 규칙(남는 원 · 10원 올림)은 서버가 한다. 여기는 화면 확인용으로 나머지를 버리는 단순 계산
function settle(r) {
  const confirmed = r.receipts.filter((rc) => rc.status === 'CONFIRMED')
  if (!confirmed.length) fail(422, 'NO_CONFIRMED_RECEIPTS', '확정된 영수증이 없어요. 영수증을 먼저 확정해주세요.')
  const paid = {}, owed = {}, pair = {}
  for (const rc of confirmed) {
    const lines = rc.items.filter((it) => it.kind === 'ITEM')
    const people = [...new Set(lines.flatMap((it) => it.member_ids))]
    const share = {}
    for (const it of lines) for (const m of it.member_ids) share[m] = (share[m] ?? 0) + Math.floor(it.amount / it.member_ids.length)
    const rest = rc.total_amount - lines.reduce((a, it) => a + it.amount, 0) // 할인 + 차액
    for (const m of people) share[m] += Math.floor(rest / people.length)
    paid[rc.payer_member_id] = (paid[rc.payer_member_id] ?? 0) + rc.total_amount
    for (const m of people) {
      owed[m] = (owed[m] ?? 0) + share[m]
      if (m !== rc.payer_member_id) pair[`${m}>${rc.payer_member_id}`] = (pair[`${m}>${rc.payer_member_id}`] ?? 0) + share[m]
    }
  }
  const name = (id) => r.members.find((m) => m.id === id).name
  const transfers = []
  for (const [k, amount] of Object.entries(pair)) {
    const [from, to] = k.split('>').map(Number)
    const net = amount - (pair[`${to}>${from}`] ?? 0) // 같은 두 사람 사이는 차이만 남긴다
    if (net > 0) transfers.push({ from: { id: from, name: name(from) }, to: { id: to, name: name(to) }, amount: net })
  }
  const version = (r.settlements.at(-1)?.version ?? 0) + 1
  const s = {
    version, created_at: now(), rounding: r.rounding, is_stale: false,
    members: r.members.map((m) => ({
      member_id: m.id, name: m.name, paid: paid[m.id] ?? 0, owed: owed[m.id] ?? 0, net: (paid[m.id] ?? 0) - (owed[m.id] ?? 0),
    })),
    transfers,
    excluded_receipts: r.receipts.filter((rc) => rc.status !== 'CONFIRMED').map(({ id, store_name }) => ({ id, store_name })),
    copy_text: [`[같이정산 · ${r.name} · 버전 ${version}]`, ...transfers.map((t) => `${t.from.name} → ${t.to.name} ${t.amount.toLocaleString('ko-KR')}원`)].join('\n'),
  }
  r.settlements.push(s)
  r.stale = false
  return s
}

const routes = [
  ['POST', /^\/rooms$/, (db, _p, body) => {
    // 진짜 서버(server/app/schemas.py RoomCreateIn)와 같은 답: 422 + 칸별 이유
    const name = body.name?.trim()
    const names = (body.members ?? []).map((n) => n.trim())
    const fields = {}
    if (!name) fields.name = '빈 값은 안 됩니다'
    names.forEach((n, i) => { if (!n) fields[`members.${i}`] = '빈 값은 안 됩니다' })
    if (names.length < 2) fields.members = '2개 이상이어야 합니다'
    if (Object.keys(fields).length) fail(422, 'VALIDATION_ERROR', '입력값을 확인해 주세요.', fields)
    // 명세서 2절 · 서버 rooms.py: 같은 이름은 구성원 추가와 같은 409
    const dup = [...new Set(names.filter((n, i) => names.indexOf(n) !== i))].sort()
    if (dup.length) fail(409, 'MEMBER_NAME_DUPLICATE', `같은 이름의 구성원이 있습니다: ${dup.join(', ')}`)
    const r = {
      room_token: newToken(), name, rounding: body.rounding ?? 'WON_1', created_at: now(),
      members: names.map((n, i) => ({ id: db.seq++, name: n, order: i + 1 })),
      receipts: [], settlements: [], stale: false,
    }
    db.rooms[r.room_token] = r
    return roomOut(r)
  }],
  ['GET', /^\/rooms\/([^/]+)$/, (_db, [r]) => roomOut(r)],
  ['PATCH', /^\/rooms\/([^/]+)$/, (_db, [r], body) => {
    if (body.rounding && body.rounding !== r.rounding) r.stale = true
    Object.assign(r, body.name ? { name: body.name } : {}, body.rounding ? { rounding: body.rounding } : {})
    return roomOut(r)
  }],
  ['GET', /^\/rooms\/([^/]+)\/receipts$/, (_db, [r]) => r.receipts.map((rc) => receiptOut(r, rc))],
  ['POST', /^\/rooms\/([^/]+)\/receipts$/, (db, [r], body) => {
    validateReceipt(r, body)
    const all = r.members.map((m) => m.id)
    const rc = {
      id: db.seq++, store_name: body.store_name?.trim() || '영수증', payer_member_id: body.payer_member_id,
      total_amount: body.total_amount, status: 'CHECKING', created_at: now(),
      items: body.items.map((it) => ({ ...it, id: db.seq++, member_ids: all })),
    }
    r.receipts.push(rc)
    return receiptOut(r, rc)
  }],
  ['GET', /^\/rooms\/([^/]+)\/receipts\/(\d+)$/, (_db, [r, rc]) => receiptOut(r, rc)],
  ['PUT', /^\/rooms\/([^/]+)\/receipts\/(\d+)$/, (db, [r, rc], body) => {
    if (rc.status === 'CONFIRMED') fail(409, 'RECEIPT_CONFIRMED', '확정된 영수증이에요. 먼저 확정 취소를 눌러주세요.')
    validateReceipt(r, body)
    const all = r.members.map((m) => m.id)
    const old = Object.fromEntries(rc.items.map((it) => [it.id, it]))
    Object.assign(rc, {
      store_name: body.store_name?.trim() || '영수증', payer_member_id: body.payer_member_id, total_amount: body.total_amount,
      // id가 있는 줄은 체크 유지, 없는 줄은 전원 체크, 보내지 않은 줄은 지움
      items: body.items.map((it) => ({ ...it, id: old[it.id] ? it.id : db.seq++, member_ids: old[it.id]?.member_ids ?? all })),
    })
    return receiptOut(r, rc)
  }],
  ['DELETE', /^\/rooms\/([^/]+)\/receipts\/(\d+)$/, (_db, [r, rc]) => {
    if (rc.status === 'CONFIRMED') fail(409, 'RECEIPT_CONFIRMED', '확정된 영수증이에요. 먼저 확정 취소를 눌러주세요.')
    r.receipts = r.receipts.filter((x) => x !== rc)
    return null
  }],
  ['POST', /^\/rooms\/([^/]+)\/receipts\/(\d+)\/confirm$/, (_db, [r, rc]) => {
    rc.status = 'CONFIRMED'
    r.stale = true
    return receiptOut(r, rc)
  }],
  ['POST', /^\/rooms\/([^/]+)\/receipts\/(\d+)\/unconfirm$/, (_db, [r, rc]) => {
    if (rc.status !== 'CONFIRMED') fail(409, 'RECEIPT_NOT_CONFIRMED', '확정된 영수증이 아니에요.')
    rc.status = 'CHECKING'
    r.stale = true
    return receiptOut(r, rc)
  }],
  ['POST', /^\/rooms\/([^/]+)\/receipts\/(\d+)\/photo$/, (_db, [r, rc], form) => {
    const file = form.get('file')
    if (!['image/jpeg', 'image/png'].includes(file.type)) fail(415, 'UNSUPPORTED_MEDIA_TYPE', 'jpg · png 사진만 올릴 수 있어요.')
    if (file.size > 10 * 1024 * 1024) fail(413, 'FILE_TOO_LARGE', '사진은 10MB 이하만 올릴 수 있어요.')
    photos[`${r.room_token}/${rc.id}`] = URL.createObjectURL(file)
    return { photo_url: photos[`${r.room_token}/${rc.id}`] }
  }],
  ['GET', /^\/rooms\/([^/]+)\/checks$/, (_db, [r]) => checksOut(r)],
  ['PUT', /^\/rooms\/([^/]+)\/checks$/, (_db, [r], body) => {
    if (body.items.some((it) => !it.member_ids.length)) fail(422, 'CHECK_EMPTY', '아무도 체크하지 않은 품목이 있어요. 품목마다 1명 이상 체크해주세요.')
    for (const { item_id, member_ids } of body.items) {
      const it = r.receipts.flatMap((rc) => rc.items).find((x) => x.id === item_id)
      if (it) it.member_ids = member_ids
    }
    r.stale = true
    return checksOut(r)
  }],
  ['POST', /^\/rooms\/([^/]+)\/settlements$/, (_db, [r]) => settle(r)],
  ['GET', /^\/rooms\/([^/]+)\/settlements\/latest$/, (_db, [r]) => {
    const s = r.settlements.at(-1)
    if (!s) fail(404, 'NOT_FOUND', '아직 계산한 결과가 없어요.')
    return { ...s, is_stale: r.stale }
  }],
]

export async function mockRequest(method, path, body) {
  const db = load()
  for (const [m, re, handler] of routes) {
    const match = m === method && path.match(re)
    if (!match) continue
    const [token, id] = match.slice(1)
    const args = []
    if (token) {
      const r = db.rooms[decodeURIComponent(token)] ?? fail(404, 'NOT_FOUND', '정산방을 찾을 수 없어요. 링크를 다시 확인해 주세요.')
      args.push(r)
      if (id) args.push(r.receipts.find((rc) => rc.id === Number(id)) ?? fail(404, 'NOT_FOUND', '영수증을 찾을 수 없어요.'))
    }
    const out = handler(db, args, body)
    storage.setItem(KEY, JSON.stringify(db))
    return structuredClone(out)
  }
  fail(404, 'NOT_FOUND', '없는 주소예요.')
}
