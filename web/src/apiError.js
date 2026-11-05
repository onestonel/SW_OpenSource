// 서버 오류 답장 {"error": {"code", "message"}}를 담는다. 화면은 message를 그대로 보여 준다
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}
