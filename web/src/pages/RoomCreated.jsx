import { Link, useParams } from 'react-router'
import { api } from '../api.js'
import { roomUrl, useCopy, useLoad } from '../hooks.js'
import { CheckIcon, CopyIcon, Loading, Page, WarnIcon } from '../ui.jsx'

export default function RoomCreated() {
  const { token } = useParams()
  const { data: room, error } = useLoad(() => api.getRoom(token), [token])
  const [copied, copy] = useCopy()
  if (!room) return <Loading error={error} />

  const url = roomUrl(token)
  return (
    <Page gap={24}>
      <div className="center-col" style={{ paddingTop: 64 }}>
        <div aria-hidden="true" className="done-circle"><CheckIcon size={34} /></div>
        <h1 className="title" style={{ fontSize: 26 }}>정산방을 만들었어요</h1>
        <p className="muted-15">{room.name} · 구성원 {room.members.length}명</p>
      </div>

      <div className="glass card-pad stack-12">
        <span className="field-label">정산방 링크</span>
        <div className="link-box">{url}</div>
        <button type="button" className="btn-secondary" onClick={() => copy(url)}>
          <CopyIcon /> 링크 복사
        </button>
        {copied && <p role="status" className="copied">링크를 복사했어요</p>}
      </div>

      <div className="notice-warn">
        <WarnIcon />
        <p>로그인이 없어서 <b>이 링크로만 다시 들어올 수 있어요.</b> 총무님이 꼭 저장해 두세요.</p>
      </div>

      <div className="spacer" />
      <Link to={`/rooms/${token}`} className="btn-primary">링크 저장했어요, 정산방으로</Link>
    </Page>
  )
}
