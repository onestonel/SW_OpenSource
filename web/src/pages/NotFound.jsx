import { Link } from 'react-router'
import { Page } from '../ui.jsx'

export default function NotFound() {
  return (
    <Page>
      <h1 className="title">없는 화면이에요</h1>
      <p className="muted-14">주소를 다시 확인해 주세요.</p>
      <Link to="/" className="btn-secondary">처음으로</Link>
    </Page>
  )
}
