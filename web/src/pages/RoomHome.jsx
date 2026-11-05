import { Link, useParams } from 'react-router'
import { api, won } from '../api.js'
import { useLoad } from '../hooks.js'
import { Loading, Page, StatusBadge } from '../ui.jsx'

export default function RoomHome() {
  const { token } = useParams()
  const { data, error } = useLoad(() => Promise.all([api.getRoom(token), api.listReceipts(token)]), [token])
  if (!data) return <Loading error={error} />

  const [room, receipts] = data
  const confirmed = receipts.filter((r) => r.status === 'CONFIRMED').length
  const s = room.latest_settlement
  const base = `/rooms/${token}`

  return (
    <Page>
      <div className="row-between">
        <span className="muted-14 strong">같이정산</span>
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
          {room.members.map((m) => <span key={m.id} className="chip">{m.name}</span>)}
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
