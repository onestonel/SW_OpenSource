import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { checkHealth } from '../api.js'

// 첫 화면 미리보기: 명세서 예시 1의 실제 결과 (민수가 항공권 · 식당을 내고, 수아는 술을 안 마심)

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
            모든 정산
            <br />
            AI와 함께해요
          </h1>
          <p>여행, 데이트, 회식까지 어떤 정산이든 AI로 정산할 수 있어요</p>
        </section>

        <ol className="receipt steps" style={{ margin: 0 }}>
          <li><span className="steps__num">1</span>정산방 만들기</li>
          <li><span className="steps__num">2</span>AI와 정산하기</li>
          <li><span className="steps__num">3</span>결과 공유하기</li>
        </ol>

        <div className="spacer" />

        <Link to="/rooms/new" className="btn-primary">정산방 만들기</Link>
      </div>
    </main>
  )
}
