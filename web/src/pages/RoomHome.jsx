import { Link, useParams } from 'react-router'
import { api, won } from '../api.js'
import { useLoad, useMe } from '../hooks.js'
import { BackLink, Loading, Page, StatusBadge } from '../ui.jsx'

const Chevron = () => (
  <svg aria-hidden="true" className="nav-card__chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 6l6 6-6 6" /></svg>
)

export default function RoomHome() {
  const { token } = useParams()
  const { data, error } = useLoad(() => Promise.all([api.getRoom(token), api.listReceipts(token)]), [token])
  if (!data) return <Loading error={error} />
  return <Room room={data[0]} receipts={data[1]} />
}

// 정산방에 처음 들어오면(이 브라우저에 고른 사람이 없으면) 구성원 중 누구인지 먼저 묻는다. 이름을 누르면 바로 들어간다
function WhoAmI({ room, onPick }) {
  return (
    <Page gap={20}>
      <BackLink to="/" label="처음 화면으로" />
      <h1 className="title">{room.name}</h1>
      <div className="field">
        <span id="me-pick" className="field-label">본인의 이름을 골라주세요</span>
        <div role="group" aria-labelledby="me-pick" className="payer-grid">
          {room.members.map((m) => (
            <button key={m.id} type="button" className="payer-btn" onClick={() => onPick(m.id)}>{m.name}</button>
          ))}
        </div>
      </div>
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
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </Link>
      </div>

      <div className="stack-10">
        <h1 className="title">{room.name}</h1>
        <div className="chips">
          {room.members.map((m) => <span key={m.id} className={`chip${m.id === me ? ' chip--me' : ''}`}>{m.name}</span>)}
        </div>
      </div>

      <div className="row-between" style={{ marginTop: 8, alignItems: 'baseline' }}>
        <h2 className="subtitle">영수증</h2>
        {receipts.length > 0 && <span className="muted-13">확정 {confirmed} · 확인 중 {receipts.length - confirmed}</span>}
      </div>

      <div className="stack-10">
        {receipts.length === 0 && <p className="card card-pad muted-14" style={{ margin: 0, textAlign: 'center' }}>아직 영수증이 없어요</p>}
        {receipts.map((r) => (
          <Link key={r.id} to={`${base}/receipts/${r.id}`} className="card receipt-card">
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
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          영수증 넣기
        </Link>
      </div>

      <nav className="card nav-list" aria-label="정산 단계">
        <Link to={`${base}/split`} className="nav-card">
          <span aria-hidden="true" className="nav-card__icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M8 12l3 3 5-6" /></svg>
          </span>
          <span className="stack-4">
            <span className="strong-16">정산 조건</span>
          </span>
          <Chevron />
        </Link>
        <Link to={`${base}/result`} className="nav-card">
          <span aria-hidden="true" className="nav-card__icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h13l-3-3" /><path d="M20 17H7l3 3" /></svg>
          </span>
          <span className="stack-4">
            <span className="strong-16">정산 결과</span>
            <span className="muted-13">{s ? `버전 ${s.version} · ${s.is_stale ? '최신 아님' : '최신'}` : '아직 계산 전'}</span>
          </span>
          <Chevron />
        </Link>
      </nav>
    </Page>
  )
}
