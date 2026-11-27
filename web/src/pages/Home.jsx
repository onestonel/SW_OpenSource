import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { checkHealth } from '../api.js'

// 첫 화면 미리보기: 명세서 예시 1의 실제 결과 (민수가 항공권 · 식당을 내고, 수아는 술을 안 마심)
const PREVIEW_RECEIPTS = [['항공권', '400,000'], ['식당', '150,000']]
const PREVIEW_TRANSFERS = [['지영 → 민수', '145,000'], ['현우 → 민수', '145,000'], ['수아 → 민수', '115,000']]

const STATUS_TEXT = {
  checking: '서버 확인 중…',
  ok: '서버 연결됨',
  db: '서버 연결됨 · DB 연결 안 됨',
  fail: '서버 연결 안 됨',
}

function ServerStatus() {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    checkHealth().then(setStatus)
  }, [])

  return (
    <p className={`server-status server-status--${status}`} role="status">
      <span className="server-status__dot" aria-hidden="true" />
      {STATUS_TEXT[status]}
    </p>
  )
}

export default function Home() {
  return (
    <main className="page">
      <div className="page-inner">
        <header className="brand">
          <div className="brand__logo" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" />
              <path d="M9 8h6" />
              <path d="M9 12h6" />
            </svg>
          </div>
          <span className="brand__name">같이정산</span>
          <ServerStatus />
        </header>

        <section className="hero">
          <h1>
            함께 쓴 돈,
            <br />
            항목별로 나눠요
          </h1>
          <p>영수증을 입력하고 품목마다 함께한 사람을 체크하면, 누가 누구에게 얼마를 보내면 되는지 정리해 드려요</p>
        </section>

        {/* 이 앱이 만드는 결과를 그대로 보여 준다: 영수증 한 장 */}
        <figure className="receipt" style={{ margin: 0 }} aria-label="정산 결과 예시">
          <div className="receipt__head">
            <span className="receipt__title">제주 여행 · 정산</span>
            <span>예시</span>
          </div>
          <hr className="receipt__rule" />
          {PREVIEW_RECEIPTS.map(([name, amount]) => (
            <div key={name} className="receipt__row muted"><span>{name} · 민수 결제</span><span>{amount}</span></div>
          ))}
          <hr className="receipt__rule" />
          {PREVIEW_TRANSFERS.map(([who, amount]) => (
            <div key={who} className="receipt__row strong"><span>{who}</span><span>{amount}원</span></div>
          ))}
          <hr className="receipt__rule" />
          <figcaption className="receipt__foot">영수증 입력 → 품목마다 체크 → 송금 목록 복사</figcaption>
        </figure>

        <div className="spacer" />

        <Link to="/rooms/new" className="btn-primary">새 정산방 만들기</Link>
        <p className="footnote">
          로그인 없이 써요. 이미 만든 정산방은
          <br />
          총무님이 저장한 링크로 다시 들어오세요
        </p>
      </div>
    </main>
  )
}
