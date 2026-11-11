// 서버 오류 답장 {"error": {"code", "message", "details"}}를 담는다.
// 화면은 message를 그대로 보여 주고, 입력 검사 실패면 details.fields(칸별 이유)도 같이 보여 준다
export class ApiError extends Error {
  constructor(status, code, message, fields = null) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}
