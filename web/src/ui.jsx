import { Link } from 'react-router'

export function Page({ children, gap = 18 }) {
  return (
    <main className="page">
      <div className="page-inner page-inner--sub" style={{ gap }}>{children}</div>
    </main>
  )
}

export function BackLink({ to, label = '뒤로' }) {
  return (
    <Link to={to} aria-label={label} className="icon-btn">
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 18l-6-6 6-6" />
      </svg>
    </Link>
  )
}

export const WarnIcon = () => (
  <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#B45309" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none', marginTop: 1 }}>
    <path d="M12 9v4" /><path d="M12 17h.01" />
    <path d="M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </svg>
)

export const CheckIcon = ({ size = 18 }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
)

export const CopyIcon = () => (
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" />
  </svg>
)

export const StatusBadge = ({ status }) =>
  status === 'CONFIRMED'
    ? <span className="badge badge--ok">확정</span>
    : <span className="badge badge--checking">확인 중</span>

// 서버 message와 함께, 입력 검사 실패면 칸별 이유(details.fields)를 보여 준다.
// labels: 칸 이름 → 화면 이름. "members.1"은 "구성원 2", "items.0.amount"는 "품목 1 금액"으로 보여 준다
export function ErrorText({ error, labels = {} }) {
  if (!error) return null
  const reasons = Object.entries(error.fields ?? {}).map(([key, why]) => {
    const name = key.split('.').map((p) => (/^\d+$/.test(p) ? Number(p) + 1 : labels[p] ?? p)).join(' ')
    return `${name}: ${why}`
  })
  return (
    <div className="error-text" role="alert">
      <p>{error.message}</p>
      {reasons.length > 0 && <ul>{reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
    </div>
  )
}

// 로딩 · 오류(없는 정산방 등)를 한 번에 처리한다
export function Loading({ error, back = '/' }) {
  return (
    <Page>
      <BackLink to={back} />
      {error ? <ErrorText error={error} /> : <p className="muted" role="status">불러오는 중…</p>}
    </Page>
  )
}

// 원 단위 토글 (정산방 만들기 · 설정): 켜면 WON_10
export function RoundingSwitch({ value, onChange, disabled }) {
  const on = value === 'WON_10'
  return (
    <div className="glass card-pad stack-10">
      <div className="row-between">
        <span aria-hidden="true" className="strong-16">10원 단위로 올리기</span>
        <button
          type="button" role="switch" aria-checked={on} aria-label="10원 단위로 올리기" disabled={disabled}
          className={`switch${on ? ' switch--on' : ''}`} onClick={() => onChange(on ? 'WON_1' : 'WON_10')}
        >
          <span aria-hidden="true" className="switch__knob" />
        </button>
      </div>
      <p className="muted-14">
        {on
          ? '켜짐: 1인 금액을 10원 단위로 올리고, 남는 돈은 결제자가 가져가요.'
          : '꺼짐(기본): 1원 단위로 나누고, 남는 1원은 구성원 순서대로 한 명씩 더 내요.'}
      </p>
    </div>
  )
}
