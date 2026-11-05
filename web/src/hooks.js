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
