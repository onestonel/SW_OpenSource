# llm — 자연어 분담 조건 해석 (V3 준비)

"D는 술을 안 마셨어" 같은 문장을 분담 규칙 JSON으로 바꾸는 부분입니다.
V1 · V2에서는 쓰지 않고, 지금은 **어떤 모델로 할지 정하는 시험 도구**만 있습니다.

| 파일 | 하는 일 |
| --- | --- |
| `bench.py` | 평가 문장 10개를 모델에 보내고, 맞힌 개수와 응답 시간을 표로 출력 |
| `eval_sentences.jsonl` | 평가 문장 10개와 정답 JSON |
| `mock_server.py` | 모델 없이 `bench.py`가 도는지 확인하는 가짜 서버 |

파이썬 기본 라이브러리만 써서 따로 설치할 것이 없습니다.

## 정해 둔 방향

- 모델은 **llama.cpp 서버(`llama-server`)를 별도 컨테이너로** 띄우고, 서버(FastAPI)는 HTTP로 부릅니다.
- 출력은 **JSON schema로 모양을 고정**합니다. 모델이 schema 밖의 글자를 만들 수 없어서 JSON이 깨지지 않습니다.
- 첫 후보는 EXAONE 3.5 2.4B, 두 번째 후보는 Qwen3 4B입니다.
- 판정 기준: **10개 중 8개 이상 맞고 평균 15초 이하**면 그 모델로 V3를 진행합니다.
  둘 다 미달이면 같은 형식의 외부 API로 바꿉니다 (`bench.py`도 그대로 씁니다).

## 노트북에서 시험하기 (Windows)

1. llama.cpp 설치
   ```powershell
   winget install llama.cpp
   ```
   winget이 안 되면 https://github.com/ggml-org/llama.cpp/releases 에서 `win-cpu-x64` zip을 받아 압축을 풀고 그 폴더에서 실행합니다.

2. 모델을 받으면서 서버 켜기 (처음 한 번은 모델 다운로드로 몇 분 걸립니다)
   ```powershell
   llama-server -hf LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct-GGUF:Q4_K_M --port 8080
   ```
   `server is listening` 이 보이면 준비된 것입니다. 모델 이름이 맞지 않는다는 오류가 나면 Hugging Face에서 모델 이름을 검색해 바꿉니다.

3. 새 터미널을 열고 시험 돌리기
   ```powershell
   cd llm
   python bench.py --base-url http://localhost:8080/v1 --out results-exaone.md
   ```

4. 두 번째 후보도 같은 방법으로 (서버를 끄고 다시 켭니다)
   ```powershell
   llama-server -hf Qwen/Qwen3-4B-GGUF:Q4_K_M --port 8080
   python bench.py --base-url http://localhost:8080/v1 --out results-qwen3.md
   ```

결과 표(`results-*.md`)를 노션 "LLM 서버 따로 필요한가" 페이지에 붙여 넣습니다.

## 모델 없이 도구만 확인하기

```bash
python mock_server.py --port 8081
python bench.py --base-url http://localhost:8081/v1     # 10/10이 나와야 정상
```

## 외부 API와 비교하기

OpenAI 형식 API라면 같은 도구로 비교할 수 있습니다.

```bash
python bench.py --base-url https://api.openai.com/v1 --model <모델 이름> --api-key <키> --plain-openai
```

API 키는 저장소에 올리지 마세요.

## 규칙 JSON 모양

```json
{
  "status": "PARSED",
  "proposals": [
    {"receipt_item_id": 201, "type": "EXCLUDE", "params": {"member_ids": [4]}, "evidence": "D는 술을 안 마셨어"}
  ],
  "clarification": null
}
```

- `status`: `PARSED` (해석함) · `NEEDS_CLARIFICATION` (다시 물어봐야 함) · `UNSUPPORTED` (정산과 관계없는 문장)
- `type`: `EQUAL` 지정한 사람끼리 똑같이 · `EXCLUDE` 몇 명 빼고 똑같이 · `FULL` 한 명이 전부 · `WEIGHTED` 비율 · `QUANTITY` 먹은 수량
- 사람과 항목은 이름이 아니라 **id 숫자**로만 가리킵니다. 서버가 받은 뒤 id가 실제로 있는지 한 번 더 검사합니다.
- 할인은 품목처럼 번호가 있는 한 줄이라서 "할인은 C만 받아" → `103 FULL C`처럼 규칙을 붙일 수 있습니다.
