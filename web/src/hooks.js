import { useEffect, useState } from 'react'

// 화면을 열 때 서버에서 데이터를 받는다. reload로 다시 받는다
export function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: null })
  const [n, setN] = useState(0)
  useEffect(() => {
    let live = true
    load().then((data) => live && setState({ data, error: null }), (error) => live && setState({ data: null, error }))
    return () => { live = false }
  }, [...deps, n]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, reload: () => setN((x) => x + 1), setData: (data) => setState({ data, error: null }) }
}

// 클립보드에 복사하고 copied를 켠다. 복사가 막힌 브라우저에서는 글을 직접 복사하게 띄운다
export function useCopy() {
  const [copied, setCopied] = useState(false)
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setCopied(false)
      window.prompt('아래 글을 길게 눌러 복사해 주세요.', text)
    }
  }
  return [copied, copy]
}

export const roomUrl = (token) => `${window.location.origin}/rooms/${token}`

// 로그인이 없어서, 이 브라우저에서 정산방마다 '나는 누구'(구성원 id)를 기억한다.
// 사생활 보호 모드 등에서 localStorage가 막혀도 화면은 돌아가야 해서 try로 감싼다
const meKey = (token) => `gachi-me:${token}`

export function getMe(token, members) {
  let id = null
  try { id = Number(localStorage.getItem(meKey(token))) || null } catch { /* 저장소 막힘 → 다시 묻는다 */ }
  return members.some((m) => m.id === id) ? id : null // 지워진 구성원이면 다시 묻는다
}

export function useMe(token, members) {
  const [me, setMeState] = useState(() => getMe(token, members))
  const setMe = (id) => {
    try { localStorage.setItem(meKey(token), String(id)) } catch { /* 이번 화면에서만 기억 */ }
    setMeState(id)
  }
  return [members.some((m) => m.id === me) ? me : null, setMe]
}
