import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, won } from '../api.js'
import { findMember, useLoad, useMe } from '../hooks.js'
import { BackLink, Loading, Page, StatusBadge } from '../ui.jsx'

export default function RoomHome() {
  const { token } = useParams()
  const { data, error } = useLoad(() => Promise.all([api.getRoom(token), api.listReceipts(token)]), [token])
  if (!data) return <Loading error={error} />
  return <Room room={data[0]} receipts={data[1]} />
}

// 정산방에 처음 들어오면(이 브라우저에 고른 사람이 없으면) 구성원 중 누구인지 먼저 묻는다
function WhoAmI({ room, onPick }) {
  const [name, setName] = useState('')
  const [error, setError] = useState(null)
  const submit = (e) => {
    e.preventDefault()
    const m = findMember(room.members, name)
    if (m) onPick(m.id)
    else setError(`구성원에 없는 이름이에요. 구성원: ${room.members.map((x) => x.name).join(', ')}`)
  }
  return (
    <Page gap={20}>
      <BackLink to="/" label="처음 화면으로" />
      <div className="stack-6">
        <h1 className="title">{room.name}</h1>
        <p className="muted-14">이 정산방에서 누구인지 알려 주세요. 영수증을 넣을 때 결제자를 본인으로 미리 골라 둘게요.</p>
      </div>
      <form className="stack-12" onSubmit={submit}>
        <div className="field">
          <label htmlFor="me">내 이름</label>
          <input id="me" className="input" type="text" autoComplete="off" placeholder="예: 민수" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {/* datalist는 브라우저마다 목록이 비어 보이기도 해서, 누르면 이름이 채워지는 버튼으로 보여 준다 */}
        <div role="group" aria-label="구성원 이름 넣기" className="payer-grid">
          {room.members.map((m) => (
            <button key={m.id} type="button" aria-pressed={name.trim() === m.name} className={`payer-btn${name.trim() === m.name ? ' payer-btn--on' : ''}`} onClick={() => { setName(m.name); setError(null) }}>
              {m.name}
            </button>
          ))}
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        <button type="submit" className="btn-primary" disabled={!name.trim()}>확인</button>
        <p className="muted-13">이 브라우저에만 저장돼요. 정산방 설정에서 바꿀 수 있어요.</p>
      </form>
    </Page>
  )
}

function Room({ room, receipts }) {
  const token = room.room_token
  const [me, setMe] = useMe(token, room.members)
  if (!me) return <WhoAmI room={room} onPick={setMe} />
  const confirmed = receipts.filter((r) => r.status === 'CONFIRMED').length
  const s = room.latest_settlement
  const base = `/rooms/${token}`

  return (
    <Page>
      <div className="row-between">
        <div className="row-gap-12">
          <BackLink to="/" label="처음 화면으로" />
          <span className="muted-14 strong">같이정산</span>
        </div>
        <Link to={`${base}/settings`} aria-label="정산방 설정" className="icon-btn">
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </Link>
      </div>

      <div className="stack-10">
        <h1 className="title">{room.name}</h1>
        <div className="chips">
          {room.members.map((m) => <span key={m.id} className={`chip${m.id === me ? ' chip--me' : ''}`}>{m.name}{m.id === me && ' (나)'}</span>)}
          <span className="muted-13">구성원 {room.members.length}명</span>
        </div>
      </div>

      <div className="row-between" style={{ marginTop: 6, alignItems: 'baseline' }}>
        <h2 className="subtitle">영수증</h2>
        <span className="muted-13">확정 {confirmed} · 확인 중 {receipts.length - confirmed}</span>
      </div>

      <div className="stack-10">
        {receipts.map((r) => (
          <Link key={r.id} to={`${base}/receipts/${r.id}`} className="glass receipt-card">
            <div className="stack-4 grow">
              <span className="strong-16">{r.store_name}</span>
              <span className="muted-13">결제 {r.payer.name} · 품목 {r.items.filter((it) => it.kind === 'ITEM').length}개</span>
            </div>
            <div className="receipt-card__right">
              <span className="strong-16">{won(r.total_amount)}원</span>
              <StatusBadge status={r.status} />
            </div>
          </Link>
        ))}
        <Link to={`${base}/receipts/new`} className="add-dashed">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          영수증 추가
        </Link>
      </div>
      <p className="muted-13">확정한 영수증만 정산에 들어가요.</p>

      <div className="spacer" />
      <div className="grid-2">
        <Link to={`${base}/split`} className="glass nav-card">
          <span aria-hidden="true" className="nav-card__icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M8 12l3 3 5-6" /></svg>
          </span>
          <span className="strong-16">분담 조건</span>
          <span className="muted-13">품목마다 체크</span>
        </Link>
        <Link to={`${base}/result`} className="glass nav-card">
          <span aria-hidden="true" className="nav-card__icon nav-card__icon--violet">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h13l-3-3" /><path d="M20 17H7l3 3" /></svg>
          </span>
          <span className="strong-16">정산 결과</span>
          <span className="muted-13">{s ? `버전 ${s.version} · ${s.is_stale ? '최신 아님' : '최신'}` : '아직 계산 전'}</span>
        </Link>
      </div>
    </Page>
  )
}
