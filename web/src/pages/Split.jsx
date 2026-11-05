import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, won } from '../api.js'
import { useLoad } from '../hooks.js'
import { BackLink, ErrorText, Loading, Page } from '../ui.jsx'

// ④ 분담 조건: 확정한 영수증의 품목 × 구성원 체크 표
export default function Split() {
  const { token } = useParams()
  const { data, error } = useLoad(() => Promise.all([api.getChecks(token), api.listReceipts(token)]), [token])
  if (!data) return <Loading error={error} back={`/rooms/${token}`} />
  return <Table token={token} checks={data[0]} receipts={data[1]} />
}

function Table({ token, checks, receipts }) {
  const navigate = useNavigate()
  const base = `/rooms/${token}`
  const { members, items } = checks
  const original = Object.fromEntries(items.map((it) => [it.item_id, it.member_ids]))
  const [picked, setPicked] = useState(original)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const payerOf = Object.fromEntries(receipts.map((r) => [r.id, r.payer.name]))
  const groups = [...new Set(items.map((it) => it.receipt_id))].map((rid) => items.filter((it) => it.receipt_id === rid))
  const cols = { gridTemplateColumns: `minmax(72px, 1fr) repeat(${members.length}, 44px)` }

  const toggle = (itemId, memberId) => {
    const now = picked[itemId]
    setPicked({ ...picked, [itemId]: now.includes(memberId) ? now.filter((m) => m !== memberId) : [...now, memberId] })
  }

  async function save() {
    setBusy(true)
    setError(null)
    // 바뀐 품목만 보낸다 (구성원 순서대로 정렬해서 비교)
    const order = (ids) => members.map((m) => m.id).filter((id) => ids.includes(id))
    const changed = items
      .filter((it) => order(picked[it.item_id]).join() !== order(original[it.item_id]).join())
      .map((it) => ({ item_id: it.item_id, member_ids: order(picked[it.item_id]) }))
    try {
      if (changed.length) await api.saveChecks(token, changed)
      navigate(`${base}/result`)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <Page gap={16}>
      <BackLink to={base} />
      <div className="stack-6">
        <h1 className="title">분담 조건</h1>
        <p className="muted-14">품목마다 함께한 사람을 체크하세요. 체크한 사람끼리 똑같이 나눠요. 확정한 영수증만 보여요.</p>
      </div>

      {groups.length === 0 && (
        <div className="glass card-pad stack-12">
          <p className="muted-14">아직 확정한 영수증이 없어요. 영수증을 확정하면 여기에 품목이 나와요.</p>
          <Link to={base} className="btn-secondary">정산방으로</Link>
        </div>
      )}

      {groups.map((rows) => (
        <div key={rows[0].receipt_id} className="glass check-card">
          <div className="check-grid check-grid--head" style={cols}>
            <span className="strong" style={{ fontSize: 15 }}>
              {rows[0].store_name} <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· 결제 {payerOf[rows[0].receipt_id]}</span>
            </span>
            {members.map((m) => <span key={m.id} className="check-grid__member">{m.name}</span>)}
          </div>
          {rows.map((it) => {
            const ids = picked[it.item_id]
            const empty = ids.length === 0
            return (
              <div key={it.item_id} className="check-grid check-grid--row" style={cols}>
                <div className="stack-4" style={{ gap: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 15 }}>{it.name}</span>
                  {empty
                    ? <span className="check-hint check-hint--error">최소 1명을 체크하세요</span>
                    : <span className="check-hint">{won(it.amount)} · {ids.length}명</span>}
                </div>
                {members.map((m) => {
                  const on = ids.includes(m.id)
                  return (
                    <label key={m.id} className="check-cell">
                      <input type="checkbox" className="visually-hidden" checked={on} aria-label={`${it.name} ${m.name}`} onChange={() => toggle(it.item_id, m.id)} />
                      <span aria-hidden="true" className={`check-box${on ? ' check-box--on' : ''}${empty ? ' check-box--error' : ''}`}>
                        {on && (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
                        )}
                      </span>
                    </label>
                  )
                })}
              </div>
            )
          })}
        </div>
      ))}

      {groups.length > 0 && (
        <>
          <p className="muted-13">새 품목은 전원 체크로 시작해요. 품목마다 최소 1명은 체크해야 저장돼요. 할인은 그 영수증 참여자끼리 똑같이 나눠요.</p>
          <div className="spacer" />
          <ErrorText error={error} />
          <button type="button" className="btn-primary" disabled={busy} onClick={save}>저장</button>
        </>
      )}
    </Page>
  )
}
