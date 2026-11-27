import { useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api.js'
import { BackLink, ErrorText, Page, RoundingSwitch } from '../ui.jsx'

const XIcon = () => (
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

export default function CreateRoom() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [members, setMembers] = useState(['', ''])
  const [rounding, setRounding] = useState('WON_1')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const setMember = (i, v) => setMembers(members.map((m, j) => (j === i ? v : m)))

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      // 검사(2명 이상 · 빈 이름 없음)는 서버가 하고, 화면은 서버 message를 보여 준다
      const room = await api.createRoom({ name, members, rounding })
      navigate(`/rooms/${room.room_token}/created`)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <Page gap={20}>
      <BackLink to="/" />
      <div className="stack-6">
        <h1 className="title">정산방 만들기</h1>
      </div>

      <form className="stack-20 grow" onSubmit={submit}>
        <div className="field">
          <label htmlFor="room-name">정산방 이름</label>
          <input id="room-name" className="input" type="text" placeholder="예: 제주 여행" maxLength={50} value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="field">
          <div className="row-between">
            <span id="members-label" className="field-label">구성원을 추가해주세요</span>
            <span className="muted-13">{members.length}명</span>
          </div>
          <div role="group" aria-labelledby="members-label" className="card list-box">
            {members.map((m, i) => (
              <div key={i} className="list-row">
                <span aria-hidden="true" className="list-row__num">{i + 1}</span>
                <input
                  type="text" className="input-bare" aria-label={`구성원 ${i + 1} 이름`} placeholder="이름" maxLength={20}
                  value={m} onChange={(e) => setMember(i, e.target.value)}
                />
                <button type="button" className="icon-plain" aria-label={`구성원 ${i + 1} 지우기`} onClick={() => setMembers(members.filter((_, j) => j !== i))}>
                  <XIcon />
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="btn-pill" onClick={() => setMembers([...members, ''])}>+ 사람 추가</button>
        </div>

        <div className="field">
          <RoundingSwitch value={rounding} onChange={setRounding} />
        </div>

        <div className="spacer" />
        <ErrorText error={error} labels={{ name: '정산방 이름', members: '구성원', rounding: '원 단위' }} />
        <button type="submit" className="btn-primary" disabled={busy}>만들기</button>
      </form>
    </Page>
  )
}
