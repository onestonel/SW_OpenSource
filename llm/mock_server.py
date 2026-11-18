"""모델 없이 bench.py가 잘 도는지 확인하는 가짜 서버.

평가 문장마다 정답을 그대로 돌려준다. --wrong 3 을 주면 3번 문장만 틀린 답을 준다.

    python mock_server.py --port 8081
    python bench.py --base-url http://localhost:8081/v1
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent


def load_answers():
    answers = {}
    for line in (HERE / "eval_sentences.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            answers[case["text"]] = case
    return answers


def make_handler(answers, wrong_id):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            user = body["messages"][-1]["content"]
            text = re.search(r"<문장>\n(.*)\n</문장>", user, re.S).group(1)
            case = answers.get(text)
            result = {"status": "UNSUPPORTED", "proposals": [], "clarification": None}
            if case:
                exp = case["expected"]
                result = {"status": exp["status"], "proposals": exp.get("proposals", []), "clarification": None}
                if exp["status"] == "NEEDS_CLARIFICATION":
                    result["clarification"] = {"question": "어느 항목인가요?", "missing": ["item"]}
                if case["id"] == wrong_id:
                    result = {"status": "UNSUPPORTED", "proposals": [], "clarification": None}
            payload = {"choices": [{"message": {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}}]}
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--wrong", type=int, default=0, help="이 번호의 문장은 일부러 틀린 답을 줌")
    args = parser.parse_args()
    HTTPServer(("127.0.0.1", args.port), make_handler(load_answers(), args.wrong)).serve_forever()
