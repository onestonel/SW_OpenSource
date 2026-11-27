import { Fragment, useState } from 'react'
import { useParams } from 'react-router'
import { api } from '../api.js'
import { roomUrl, useCopy, useLoad, useMe } from '../hooks.js'
import { BackLink, ErrorText, Loading, Page, RoundingSwitch } from '../ui.jsx'

// '나는 누구' 바꾸기 (정산방 홈에서 처음 고른 값)
function MePicker({ token, members }) {
  const [me, setMe] = useMe(token, members)
  return (
    <div role="group" aria-labelledby="me-label" className="payer-grid">
      {members.map((m) => (
        <button key={m.id} type="button" aria-pressed={me === m.id} className={`payer-btn${me === m.id ? ' payer-btn--on' : ''}`} onClick={() => setMe(m.id)}>
          {m.name}
        </button>
      ))}
    </div>
  )
}

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
        <RoundingSwitch value={room.rounding} onChange={changeRounding} disabled={busy} />
        <ErrorText error={saveError} />
      </div>

      <div className="field">
        <span id="me-label" className="field-label">내 이름</span>
        <MePicker token={token} members={room.members} />
      </div>

      <div className="field">
        <span className="field-label">구성원 순서</span>
        <div className="card card-pad-sm row-wrap">
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
        <div className="card card-pad-sm row-gap-12">
          <span className="ellipsis grow">{url}</span>
          <button type="button" className="btn-pill" onClick={() => copy(url)}>복사</button>
        </div>
        {copied && <p role="status" className="copied">링크를 복사했어요</p>}
        <p className="muted-13">링크를 아는 사람은 누구나 들어올 수 있어요</p>
      </div>
    </Page>
  )
}
