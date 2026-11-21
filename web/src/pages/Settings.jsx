import { Fragment, useState } from 'react'
import { useParams } from 'react-router'
import { api } from '../api.js'
import { roomUrl, useCopy, useLoad } from '../hooks.js'
import { BackLink, ErrorText, Loading, Page, RoundingSwitch } from '../ui.jsx'

export default function Settings() {
  const { token } = useParams()
  const { data: room, error, setData } = useLoad(() => api.getRoom(token), [token])
  const [saveError, setSaveError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [copied, copy] = useCopy()
  if (!room) return <Loading error={error} back={`/rooms/${token}`} />

  async function changeRounding(rounding) {
    setBusy(true)
    setSaveError(null)
    try {
      setData(await api.updateRoom(token, { rounding }))
    } catch (err) {
      setSaveError(err)
    }
    setBusy(false)
  }

  const url = roomUrl(token)
  return (
    <Page gap={20}>
      <BackLink to={`/rooms/${token}`} />
      <h1 className="title">정산방 설정</h1>

      <div className="field">
        <span className="field-label">원 단위</span>
        <RoundingSwitch value={room.rounding} onChange={changeRounding} disabled={busy} />
        <ErrorText error={saveError} />
        <p className="muted-13">바꾸면 정산 결과가 '최신 아님'으로 바뀌어요.</p>
      </div>

      <div className="field">
        <span className="field-label">구성원 순서</span>
        <div className="glass card-pad-sm row-wrap">
          {room.members.map((m, i) => (
            <Fragment key={m.id}>
              {i > 0 && <span aria-hidden="true" className="faint">›</span>}
              <span className="strong-16">{m.name}</span>
            </Fragment>
          ))}
          <span className="muted-13" style={{ marginLeft: 'auto' }}>남는 1원 순서</span>
        </div>
      </div>

      <div className="field">
        <span className="field-label">정산방 링크</span>
        <div className="glass card-pad-sm row-gap-12">
          <span className="ellipsis grow">{url}</span>
          <button type="button" className="btn-pill" onClick={() => copy(url)}>복사</button>
        </div>
        {copied && <p role="status" className="copied">링크를 복사했어요</p>}
        <p className="muted-13">이 링크가 있으면 누구나 정산방을 열 수 있어요. 총무님만 보관해 주세요.</p>
      </div>
    </Page>
  )
}
