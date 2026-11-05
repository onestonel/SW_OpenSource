import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { checkHealth } from '../api.js'

const STEPS = [
  { title: '영수증 입력', desc: '사진을 보면서 품목과 금액을 적어요' },
  { title: '체크로 분담', desc: '품목마다 함께한 사람을 골라요' },
  { title: '송금 목록 복사', desc: '단톡에 붙여 넣으면 끝' },
]

const STATUS_TEXT = {
  checking: '서버 확인 중…',
  ok: '서버 연결됨',
  fail: '서버 연결 안 됨',
}

function ServerStatus() {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    checkHealth()
      .then((ok) => setStatus(ok ? 'ok' : 'fail'))
      .catch(() => setStatus('fail'))
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
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
          <p>영수증을 입력하고 품목마다 함께한 사람을 체크하면, 누가 누구에게 얼마를 보내면 되는지 정리해 드려요.</p>
        </section>

        <ol className="steps glass">
          {STEPS.map((step, i) => (
            <li key={step.title} className="steps__item">
              <span className="steps__num" aria-hidden="true">{i + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.desc}</span>
              </div>
            </li>
          ))}
        </ol>

        <div className="spacer" />

        <Link to="/rooms/new" className="btn-primary">새 정산방 만들기</Link>
        <p className="footnote">
          로그인 없이 써요. 이미 만든 정산방은
          <br />
          총무님이 저장한 링크로 다시 들어오세요.
        </p>
      </div>
    </main>
  )
}
