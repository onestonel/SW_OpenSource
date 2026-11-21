import { useState } from 'react'
import { useParams } from 'react-router'
import { api, won } from '../api.js'
import { useCopy, useLoad } from '../hooks.js'
import { BackLink, CopyIcon, ErrorText, Loading, Page, WarnIcon } from '../ui.jsx'

// 명세의 "11/4 16:20" 모양
const when = (iso) => {
  const d = new Date(iso)
  const two = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${two(d.getHours())}:${two(d.getMinutes())}`
}

// ⑤ 정산 결과: '다시 계산'을 누를 때만 서버가 계산하고, 화면은 서버가 준 금액을 보여 주기만 한다
export default function Result() {
  const { token } = useParams()
  const base = `/rooms/${token}`
  // 한 번도 계산하지 않았으면 서버가 404를 준다 → 빈 결과로 보여 준다
  const { data, error, setData } = useLoad(
    () => api.getLatestSettlement(token).then((s) => ({ s }), (e) => (e.status === 404 && e.code === 'NOT_FOUND' ? api.getRoom(token).then(() => ({ s: null })) : Promise.reject(e))),
    [token],
  )
  const [calcError, setCalcError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [copied, copy] = useCopy()
  if (!data) return <Loading error={error} back={base} />

  const s = data.s
  async function recalc() {
    setBusy(true)
    setCalcError(null)
    try {
      setData({ s: await api.recalculate(token) })
    } catch (err) {
      setCalcError(err)
    }
    setBusy(false)
  }

  return (
    <Page gap={16}>
      <BackLink to={base} />
      <div className="row-between" style={{ alignItems: 'flex-end' }}>
        <div className="stack-4">
          <h1 className="title">정산 결과</h1>
          <span className="muted-14">{s ? `버전 ${s.version} · ${when(s.created_at)}` : '아직 계산 전'}</span>
        </div>
        <button type="button" className="btn-pill recalc-btn" disabled={busy} onClick={recalc}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></svg>
          {busy ? '계산 중…' : '다시 계산'}
        </button>
      </div>
      <ErrorText error={calcError} />

      {s?.is_stale && (
        <div className="notice-warn" role="alert" style={{ alignItems: 'center', padding: '14px 16px' }}>
          <WarnIcon />
          <b style={{ fontSize: 14, lineHeight: 1.5 }}>최신 결과가 아닙니다. 다시 계산을 눌러주세요</b>
        </div>
      )}

      {!s && <p className="glass card-pad muted-14">영수증을 확정하고 분담 조건을 정한 뒤 '다시 계산'을 눌러주세요.</p>}

      {s && (
        <>
          {s.excluded_receipts.length > 0 && (
            <p className="muted-13">확정 안 된 영수증 {s.excluded_receipts.length}개는 빠졌어요: {s.excluded_receipts.map((r) => r.store_name).join(', ')}</p>
          )}

          <section className="stack-6" style={{ gap: 8 }}>
            <h2 className="subtitle" style={{ fontSize: 16 }}>사람별</h2>
            <table className="glass result-table">
              <thead>
                <tr><th scope="col"><span className="visually-hidden">이름</span></th><th scope="col">낸 돈</th><th scope="col">내야 할 돈</th><th scope="col">결과</th></tr>
              </thead>
              <tbody>
                {s.members.map((m) => (
                  <tr key={m.member_id}>
                    <th scope="row">{m.name}</th>
                    <td>{won(m.paid)}</td>
                    <td>{won(m.owed)}</td>
                    <td className={m.net > 0 ? 'net-plus' : m.net < 0 ? 'net-minus' : ''}>
                      {m.net > 0 ? `${won(m.net)} 받음` : m.net < 0 ? `${won(-m.net)} 보냄` : '0'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="stack-6" style={{ gap: 8 }}>
            <h2 className="subtitle" style={{ fontSize: 16 }}>송금 목록</h2>
            <ul className="glass transfer-list">
              {s.transfers.length === 0 && <li className="muted-14">보낼 돈이 없어요.</li>}
              {s.transfers.map((tr) => (
                <li key={`${tr.from.id}-${tr.to.id}`}><span>{tr.from.name} → {tr.to.name}</span><span>{won(tr.amount)}원</span></li>
              ))}
            </ul>
            <p className="muted-13">
              영수증마다 '→ 결제자'를 만들고, 같은 두 사람 사이는 하나로 합쳤어요. 원 단위: {s.rounding === 'WON_10' ? '10원 올림' : '1원 (기본)'}
            </p>
          </section>

          <div className="spacer" />
          {copied && (
            <div role="status" className="copy-toast">
              <b>복사했어요. 단톡에 붙여 넣으세요</b>
              <br />
              {s.copy_text}
            </div>
          )}
          <button type="button" className="btn-primary" onClick={() => copy(s.copy_text)} style={{ gap: 8 }}>
            <CopyIcon /> 송금 목록 복사
          </button>
        </>
      )}
    </Page>
  )
}
