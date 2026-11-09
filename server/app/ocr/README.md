# ocr — 영수증 사진 자동 인식 (V2 프로토타입)

영수증 사진을 읽어 API 약속서의 **'영수증 만들기' 초안**(가게 이름 · 합계 · 품목)을 만듭니다.
사람은 '확인 중' 상태에서 초안을 고친 뒤 확정합니다. 지금은 실험 브랜치(`experiment/ocr-prototype`)에만 있습니다.

```
사진 ─▶ preprocess ─▶ engines ─▶ group_lines ─▶ parser ─▶ 초안 + check + warnings
       (회전·크기·명암)  (글자 읽기)   (줄로 묶기)    (규칙: 가게·품목·할인·합계)
```

| 파일 | 하는 일 |
| --- | --- |
| `engines.py` | OCR 엔진. `stub`(고정 답) · `tesseract` · `easyocr`. 새 엔진은 클래스 하나 + `ENGINES`에 등록 |
| `preprocess.py` | 사진 다듬기. `PreprocessOptions`로 키우기 · 명암 · 흑백 등을 켜고 끔 |
| `pipeline.py` | 전체 흐름 `run_ocr(사진 바이트) → OcrResult`, 글자 상자를 줄로 묶는 `group_lines` |
| `parser.py` | 줄 → 초안. 판단 기준은 전부 `ParseRules` 한 곳 |
| `bench.py` | 평가 데이터로 엔진 · 규칙 점수 매기기 |
| `synth.py` | 평가용 가짜 영수증 사진 그리기 |
| `samples/` | 평가 데이터: `이름.jpg` + `이름.json`(정답). `dev_`는 규칙 고칠 때 보는 것, `test_`는 처음 보는 것 |
| `../api/v1/ocr.py` | `POST /api/v1/receipt-photos/{name}/ocr` (올린 사진 이름으로 초안 받기) |

## 설치 (실제 엔진을 쓸 때만)

```powershell
pip install -r requirements-ocr.txt
```
- **Tesseract 프로그램**: Windows는 [UB-Mannheim 설치 파일](https://github.com/UB-Mannheim/tesseract/wiki)에서 설치할 때 Korean 언어를 고릅니다.
  Linux · Docker는 `apt install tesseract-ocr tesseract-ocr-kor`. 다른 경로에 설치했으면 `TESSERACT_CMD`에 exe 경로를 넣습니다.
- **EasyOCR**(비교용): `pip install easyocr`. 처음 쓸 때 한국어 모델을 내려받습니다.
- 서버 기본값은 `OCR_ENGINE=stub`이라 OCR을 설치하지 않은 팀원은 아무것도 하지 않아도 됩니다.

## 써 보기

```powershell
cd server
# 사진 한 장 읽기 (--lines: 줄마다 어떤 역할로 판단했는지)
.venv\Scripts\python -m app.ocr app\ocr\samples\dev_02.jpg --lines

# API: 서버를 켜고 /docs 에서 ① POST /receipt-photos 로 사진 올리기 ② POST /receipt-photos/{name}/ocr (engine=tesseract)
.venv\Scripts\python -m uvicorn app.main:app --reload

# 채점 (규칙을 고칠 땐 --split dev --show-errors)
.venv\Scripts\python -m app.ocr.bench --engine tesseract easyocr --out results.md
```

## 튜닝하는 곳

| 무엇 | 어디 | 예 |
| --- | --- | --- |
| 무시할 줄 · 합계 · 할인 낱말 | `parser.ParseRules` | `total_keywords`에 '총결제금액' 더하기 |
| 숫자 자리 오인식 고치기 | `ParseRules.digit_fixes` | OCR이 5를 S로 읽으면 `"S": "5"` |
| 사진 키우기 · 명암 · 흑백 | `preprocess.PreprocessOptions` | `min_width=1400`(기본, dev 비교로 정함), `threshold=150` |
| 엔진 설정 | `TesseractEngine(lang, psm, space_ratio)` | `lang="kor+eng"`, `psm=6` |
| 줄 묶기 | `run_ocr(line_tolerance=0.6)` | 기울어진 사진이 많으면 올림 |

고친 뒤에는 꼭 `bench`로 dev 점수를 비교하고, **test 점수는 마지막에 한 번만** 봅니다 (test를 보며 고치면 점수가 부풀려집니다).

## 넓히는 법

- **엔진 추가** (PaddleOCR, 외부 OCR API, 비전 LLM): `engines.py`에 `read(image) -> list[TextBox]` 클래스를 만들고 `ENGINES`에 이름을 넣으면
  API · 명령 · bench에서 바로 고를 수 있습니다.
- **LLM 파서**: `parse_receipt`와 같은 모양(줄 목록 → `ParsedReceipt`)으로 만들면 규칙 대신 쓸 수 있습니다.
  `llm/`의 JSON schema 방식과 서버 검사(품목 합 = 합계)를 그대로 쓸 수 있습니다.
- **V2 Worker**: 사진 올리기 → RabbitMQ에 사진 이름 → Worker가 볼륨 `/data/receipts`에서 사진을 읽어 `run_ocr` → 영수증 칸 채우기.
  Worker에 필요한 것은 `run_ocr` 한 줄입니다.
- **진짜 영수증 추가**: `samples/이름.jpg` + `samples/이름.json`(synth 칸 없이)을 넣으면 채점에 들어갑니다.
  카드번호 · 승인번호 · 주소는 가리고 넣습니다.

## 지금 한계

- 평가 데이터 12장은 모두 **가짜 영수증**(`synth.py`)이라 실제 폰 사진보다 쉽습니다. 실제 점수는 더 낮을 것입니다.
- 많이 기울거나 구겨진 사진, 영수증 밖 배경이 넓은 사진은 아직 보정하지 않습니다 (기울기 보정 · 영역 자르기 필요).
- 품목의 수량은 `lines`에만 있고 초안에는 없습니다 (약속서 품목 칸에 수량이 없어서).
- 요청 안에서 OCR을 기다립니다 (Tesseract 약 0.6초). V2에서는 Worker로 옮깁니다.
