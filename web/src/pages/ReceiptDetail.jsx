import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, photoSrc, won } from '../api.js'
import { useLoad } from '../hooks.js'
import { BackLink, CheckIcon, ErrorText, Loading, Page, StatusBadge, WarnIcon } from '../ui.jsx'

// ③ 확인 · 확정: 확인 중이면 고치기 · 확정 · 지우기, 확정이면 확정 취소만
export default function ReceiptDetail() {
  const { token, id } = useParams()
  const navigate = useNavigate()
  const base = `/rooms/${token}`
  const { data: r, error, setData } = useLoad(() => api.getReceipt(token, id), [token, id])
  const [actionError, setActionError] = useState(null)
  const [busy, setBusy] = useState(false)
  if (!r) return <Loading error={error} back={base} />

  async function run(action) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
    } catch (err) {
      setActionError(err)
    }
    setBusy(false)
  }
  const confirm = () => run(async () => setData(await api.confirmReceipt(token, r.id)))
  const unconfirm = () => run(async () => setData(await api.unconfirmReceipt(token, r.id)))
  const remove = () => {
    if (!window.confirm(`'${r.store_name}' 영수증을 지울까요?`)) return
    run(async () => {
      await api.deleteReceipt(token, r.id)
      navigate(base, { replace: true })
    })
  }

  const confirmed = r.status === 'CONFIRMED'
  const { items_sum, difference, is_matched } = r.check
  return (
    <Page>
      <BackLink to={base} label="정산방으로" />
      <div className="row-gap-12" style={{ gap: 10 }}>
        <h1 className="title">{r.store_name}</h1>
        <StatusBadge status={r.status} />
      </div>
      <p className="muted-14" style={{ marginTop: -10 }}>
        결제 {r.payer.name} · {confirmed ? '정산에 들어가요' : r.photo_url ? '영수증 사진 있음' : '사진 없음'}
      </p>

      {r.photo_url && <img src={photoSrc(r.photo_url)} alt="올린 영수증 사진" className="glass detail-photo" />}

      <div className="glass lines-card">
        {r.items.map((it) => (
          <div key={it.id} className={`line${it.kind === 'DISCOUNT' ? ' line--discount' : ''}`}>
            <span>{it.name}</span><span>{won(it.amount)}</span>
          </div>
        ))}
        {confirmed && <div className="line line--total"><span>총액</span><span>{won(r.total_amount)}원</span></div>}
      </div>

      {confirmed ? (
        <div className="notice-plain">
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#55555C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none', marginTop: 2 }}>
            <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />
          </svg>
          <p>확정한 영수증은 바로 고치거나 지울 수 없어요. <b>확정 취소</b>를 누르면 '확인 중'으로 돌아가고, 그때 고치거나 지울 수 있어요.</p>
        </div>
      ) : (
        <>
          <div className="grid-2" style={{ gap: 10 }}>
            <div className="sum-box"><span className="muted-13">품목 합</span><span className="sum-box__value">{won(items_sum)}원</span></div>
            <div className="sum-box"><span className="muted-13">총액</span><span className="sum-box__value">{won(r.total_amount)}원</span></div>
          </div>
          {is_matched ? (
            <div className="notice-ok"><CheckIcon size={20} /> 품목 합과 총액이 같아요</div>
          ) : (
            <div className="notice-warn" role="alert">
              <WarnIcon />
              <div className="stack-4">
                <b style={{ fontSize: 15 }}>품목 합 ≠ 총액 ({won(Math.abs(difference))}원 차이)</b>
                <p>확정은 할 수 있어요. 정산은 총액 기준이라, 차액은 이 영수증 참여자끼리 똑같이 나눠요.</p>
              </div>
            </div>
          )}
        </>
      )}

      <div className="spacer" />
      <ErrorText error={actionError} />
      {confirmed ? (
        <>
          <button type="button" className="btn-secondary btn-secondary--lg btn-danger" disabled={busy} onClick={unconfirm}>확정 취소</button>
          <Link to={base} className="btn-primary">정산방으로</Link>
        </>
      ) : (
        <>
          <div className="grid-2" style={{ gap: 10 }}>
            <Link to={`${base}/receipts/${r.id}/edit`} className="btn-secondary btn-secondary--lg">고치기</Link>
            <button type="button" className="btn-primary" disabled={busy} onClick={confirm}>확정</button>
          </div>
          <p className="muted-13" style={{ textAlign: 'center' }}>확정한 영수증만 정산에 들어가요.</p>
          <button type="button" className="btn-text" disabled={busy} onClick={remove}>영수증 지우기</button>
        </>
      )}
    </Page>
  )
}
