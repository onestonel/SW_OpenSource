import { useParams } from 'react-router'
import { api, providerLabel } from '../api.js'
import { useLoad } from '../hooks.js'
import { BackLink, Loading, Page } from '../ui.jsx'

// 기록 화면은 기술 화면이라 JSON과 같은 영어 코드로 보여 준다 (대화창은 한국어)
const LABEL = { NEEDS_CLARIFICATION: 'ASK', PARSED: 'PARSED', '(없음)': '(없음)' }
const OUTCOME = { APPLIED: '반영', MOVED_ON: '반영 안 함', ANSWERED: '답함', '결과 없음': '아직' }
const pct = (x) => (x == null ? '-' : `${Math.round(x * 100)}%`)
const label = (k) => LABEL[k] ?? k

// AI 총무 기록: AI가 어떻게 알아들었고, 서버가 무엇을 고쳤고, 사용자가 받아들였는지 (AI가 어디서 틀리는지 찾는 용도)
export default function AiLog() {
  const { token } = useParams()
  const { data, error } = useLoad(() => api.getAiLog(token), [token])
  if (!data) return <Loading error={error} back={`/rooms/${token}/split`} />
  const { summary: s, entries } = data
  const m = s.rule_matrix
  const names = (ids) => ids.length

  return (
    <Page>
      <BackLink to={`/rooms/${token}/split`} label="분담 조건" />
      <div className="stack-6">
        <h1 className="title">AI 총무 기록</h1>
        <p className="muted-14">AI가 말을 어떻게 알아들었는지, 서버가 무엇을 고쳤는지, 사용자가 받아들였는지 모았어요.</p>
      </div>

      <section className="ailog-stats">
        <div className="glass card-pad"><span className="muted-13">말한 횟수</span><b>{s.total}</b></div>
        <div className="glass card-pad"><span className="muted-13">반영 비율</span><b>{pct(s.apply_rate)}</b><span className="muted-13">{s.applied}/{s.proposals}</span></div>
        <div className="glass card-pad"><span className="muted-13">반영 뒤 손으로 고침</span><b>{pct(s.fix_rate)}</b><span className="muted-13">{s.fixed_after_apply}/{s.applied}</span></div>
        <div className="glass card-pad"><span className="muted-13">GPT로 넘김</span><b>{s.escalated}</b><span className="muted-13">작은 모델이 못 알아들은 말</span></div>
        <div className="glass card-pad"><span className="muted-13">서버가 고친 답</span><b>{s.repaired_entries}</b><span className="muted-13">{Object.entries(s.repairs).map(([k, v]) => `${k} ${v}`).join(', ') || '없음'}</span></div>
      </section>

      {m.rows.length > 0 && (
        <section className="stack-6" style={{ gap: 8 }}>
          <h2 className="subtitle" style={{ fontSize: 16 }}>규칙 표</h2>
          <p className="muted-13">행은 모델이 고른 규칙, 열은 서버가 고친 뒤 규칙이에요. 대각선 밖의 숫자가 서버가 바로잡은 횟수예요. EQUAL 일부만 부담 · EXCLUDE 제외 · FULL 전액 부담 · PAID 송금 완료 · ASK 추가 질문</p>
          <div className="glass card-pad" style={{ overflowX: 'auto' }}>
            <table className="ailog-matrix">
              <thead><tr><th>모델 \ 최종</th>{m.cols.map((c) => <th key={c}>{label(c)}</th>)}</tr></thead>
              <tbody>
                {m.rows.map((r, i) => (
                  <tr key={r}>
                    <th>{label(r)}</th>
                    {m.cells[i].map((v, j) => <td key={m.cols[j]} className={v && r !== m.cols[j] ? 'off' : v ? 'on' : ''}>{v || ''}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="stack-6" style={{ gap: 8 }}>
        <h2 className="subtitle" style={{ fontSize: 16 }}>기록</h2>
        {entries.length === 0 && <p className="muted-14">아직 AI 총무에게 말한 적이 없어요.</p>}
        <ul className="glass ailog-list">
          {entries.map((e) => (
            <li key={e.id}>
              <span className="strong">{e.text}</span>
              <span className="muted-13">
                {e.model_rules.map(label).join(', ')}
                {e.repairs.length > 0 && <> → <b style={{ color: 'var(--text)' }}>{e.final_rules.map(label).join(', ')}</b> (서버 보정)</>}
                {' · '}{e.status === 'PARSED' && e.changes.length === 0 ? '바꿀 것 없음' : OUTCOME[e.outcome ?? '결과 없음']}
                {e.provider !== 'stub' && ` · ${providerLabel(e.provider)} ${(e.elapsed_ms / 1000).toFixed(1)}초`}
              </span>
              {e.manual_fixes.length > 0 && (
                <span className="ailog-fix">반영 뒤 손으로 고침: {e.manual_fixes.map((f) => `${f.name} (AI ${names(f.ai_member_ids)}명 → ${names(f.user_member_ids)}명)`).join(', ')}</span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </Page>
  )
}
