import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, photoSrc, won } from '../api.js'
import { useLoad } from '../hooks.js'
import { BackLink, CheckIcon, ErrorText, Loading, Page } from '../ui.jsx'

const XIcon = () => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

const digits = (s) => s.replace(/\D/g, '')
const money = (s) => (s ? won(Number(s)) : '')
let nextKey = 0
const emptyLine = (kind = 'ITEM') => ({ key: `new-${nextKey++}`, name: kind === 'DISCOUNT' ? '할인' : '', amount: '', kind })

// 서버 영수증 → 입력칸 (할인은 마이너스지만 칸에는 양수로 보여 준다)
const toForm = (r) => ({
  store: r.store_name,
  payer: r.payer.id,
  total: String(r.total_amount),
  lines: r.items.map((it) => ({ key: String(it.id), id: it.id, name: it.name, amount: String(Math.abs(it.amount)), kind: it.kind })),
  photoUrl: photoSrc(r.photo_url),
})

export default function ReceiptForm() {
  const { token, id } = useParams()
  const { data, error } = useLoad(() => Promise.all([api.getRoom(token), id ? api.getReceipt(token, id) : null]), [token, id])
  if (!data) return <Loading error={error} back={`/rooms/${token}`} />
  return <Form room={data[0]} receipt={data[1]} />
}

function Form({ room, receipt }) {
  const navigate = useNavigate()
  const base = `/rooms/${room.room_token}`
  const init = receipt ? toForm(receipt) : { store: '', payer: null, total: '', lines: [emptyLine()], photoUrl: null }
  const [store, setStore] = useState(init.store)
  const [payer, setPayer] = useState(init.payer)
  const [lines, setLines] = useState(init.lines)
  const [total, setTotal] = useState(init.total)
  const [photo, setPhoto] = useState(null) // 새로 고른 사진 파일
  const [preview, setPreview] = useState(init.photoUrl)
  const [bigPhoto, setBigPhoto] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => () => { if (photo) URL.revokeObjectURL(preview) }, [photo, preview])

  const setLine = (key, patch) => setLines(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const signed = (l) => (l.kind === 'DISCOUNT' ? -1 : 1) * Number(l.amount || 0)
  // 입력 확인용 합계 표시 (정산 계산은 서버가 한다)
  const sum = lines.reduce((a, l) => a + signed(l), 0)
  const matched = total !== '' && sum === Number(total)

  function pickPhoto(e) {
    const file = e.target.files[0]
    if (!file) return
    setPhoto(file)
    setPreview(URL.createObjectURL(file))
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const body = {
      store_name: store,
      // 결제자를 안 골랐으면 빼서 보낸다 (null이면 서버가 "정수여야 합니다", 빼면 "필수")
      ...(payer ? { payer_member_id: payer } : {}),
      total_amount: Number(total || 0),
      items: lines.map((l) => ({ ...(l.id ? { id: l.id } : {}), name: l.name, amount: signed(l), kind: l.kind })),
    }
    try {
      const saved = receipt ? await api.updateReceipt(room.room_token, receipt.id, body) : await api.createReceipt(room.room_token, body)
      if (photo) await api.uploadPhoto(room.room_token, saved.id, photo)
      navigate(`${base}/receipts/${saved.id}`, { replace: true })
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <Page gap={16}>
      <div className="row-gap-12">
        <BackLink to={receipt ? `${base}/receipts/${receipt.id}` : base} />
        <h1 className="title" style={{ fontSize: 24 }}>{receipt ? '영수증 고치기' : '영수증 추가'}</h1>
      </div>

      {/* 사진은 크게 보기를 켜면 위에 붙어 있어서, 스크롤하며 입력칸과 같이 볼 수 있다 */}
      <div className={`glass photo-card${bigPhoto ? ' photo-card--big' : ''}`}>
        {preview
          ? <img src={preview} alt="올린 영수증 사진" className="photo-card__img" />
          : <div aria-hidden="true" className="photo-card__empty" />}
        {!bigPhoto && (
          <div className="stack-4 grow">
            <span className="strong" style={{ fontSize: 15 }}>영수증 사진 <span className="muted" style={{ fontWeight: 400 }}>(선택)</span></span>
            <span className="muted-13" style={{ lineHeight: 1.5 }}>사진을 보면서 아래 칸을 채워요. 자동 인식은 V2에서 돼요.</span>
          </div>
        )}
        <div className="photo-card__actions">
          <label className="btn-pill">
            {preview ? '바꾸기' : '사진 올리기'}
            <input type="file" accept="image/jpeg,image/png" className="visually-hidden" onChange={pickPhoto} />
          </label>
          {preview && (
            <button type="button" className="btn-pill" aria-pressed={bigPhoto} onClick={() => setBigPhoto(!bigPhoto)}>
              {bigPhoto ? '작게 보기' : '크게 보기'}
            </button>
          )}
        </div>
      </div>

      <form className="stack-20 grow" style={{ gap: 16 }} onSubmit={submit}>
        <div className="field">
          <label htmlFor="store">가게 이름</label>
          <input id="store" className="input" type="text" placeholder="예: 1차 식당" value={store} onChange={(e) => setStore(e.target.value)} />
        </div>

        <div className="field">
          <span id="payer-label" className="field-label">결제자</span>
          <div role="group" aria-labelledby="payer-label" className="payer-grid">
            {room.members.map((m) => (
              <button key={m.id} type="button" aria-pressed={payer === m.id} className={`payer-btn${payer === m.id ? ' payer-btn--on' : ''}`} onClick={() => setPayer(m.id)}>
                {m.name}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span className="field-label">품목</span>
          <div className="glass list-box">
            {lines.map((l, i) => (
              <div key={l.key} className="list-row">
                <input
                  type="text" className="input-bare" aria-label={`품목 ${i + 1} 이름`} placeholder={l.kind === 'DISCOUNT' ? '할인' : '품목 이름'}
                  value={l.name} onChange={(e) => setLine(l.key, { name: e.target.value })}
                />
                {l.kind === 'DISCOUNT' && <span aria-hidden="true" className="discount-sign">−</span>}
                <input
                  type="text" inputMode="numeric" className={`input-bare amount${l.kind === 'DISCOUNT' ? ' amount--discount' : ''}`}
                  aria-label={`품목 ${i + 1} ${l.kind === 'DISCOUNT' ? '할인 금액' : '금액'}`} placeholder="0"
                  value={money(l.amount)} onChange={(e) => setLine(l.key, { amount: digits(e.target.value) })}
                />
                <button type="button" className="icon-plain" aria-label={`품목 ${i + 1} 지우기`} onClick={() => setLines(lines.filter((x) => x.key !== l.key))}>
                  <XIcon />
                </button>
              </div>
            ))}
            <div className="line-actions">
              <button type="button" className="chip-btn" onClick={() => setLines([...lines, emptyLine()])}>+ 품목 추가</button>
              <button type="button" className="chip-btn chip-btn--gray" onClick={() => setLines([...lines, emptyLine('DISCOUNT')])}>+ 할인 (−금액)</button>
            </div>
          </div>
        </div>

        <div className="field">
          <label htmlFor="total">총액 <span className="muted" style={{ fontWeight: 400 }}>(영수증에 찍힌 금액)</span></label>
          <input
            id="total" className="input input--total" type="text" inputMode="numeric" placeholder="0"
            value={money(total)} onChange={(e) => setTotal(digits(e.target.value))}
          />
        </div>

        {total !== '' && (
          matched
            ? <p className="sum-line sum-line--ok"><CheckIcon /> 품목 합 {won(sum)}원 = 총액 {won(Number(total))}원</p>
            : <p className="sum-line sum-line--warn">품목 합 {won(sum)}원 ≠ 총액 {won(Number(total))}원 · 달라도 저장돼요</p>
        )}

        <div className="spacer" />
        <ErrorText
          error={error}
          labels={{ store_name: '가게 이름', payer_member_id: '결제자', total_amount: '총액', items: '품목', name: '이름', amount: '금액' }}
        />
        <button type="submit" className="btn-primary" disabled={busy}>저장</button>
        <p className="muted-13" style={{ textAlign: 'center' }}>저장하면 '확인 중' 상태가 돼요. 합이 안 맞아도 저장돼요.</p>
      </form>
    </Page>
  )
}
