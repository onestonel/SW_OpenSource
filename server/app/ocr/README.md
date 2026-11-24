# ocr — 영수증 사진 자동 인식 (V2 프로토타입)

영수증 사진을 읽어 API 약속서의 **'영수증 만들기' 초안**(가게 이름 · 합계 · 품목)을 만듭니다.
사람은 '확인 중' 상태에서 초안을 고친 뒤 확정합니다. 개선 과정(문제 → 원인 → 해결 → 점수)은 [OCR 개선 보고서](../../../docs/ocr-report.md)에 쌓습니다.

```
사진 ─▶ preprocess ─▶ engines ─▶ group_lines ─▶ parser ─▶ 초안 + check + warnings
       (회전·크기·명암)  (글자 읽기)   (줄로 묶기)    (표의 열 나누기 → 규칙 → 산수 검산)
```

| 파일 | 하는 일 |
| --- | --- |
| `engines.py` | OCR 엔진. `stub`(고정 답) · `tesseract` · `easyocr` · `paddleocr`. 새 엔진은 클래스 하나 + `ENGINES`에 등록. 글자 상자에 낱말 위치(`words`)를 담으면 표 읽기에 쓰임 |
| `preprocess.py` | 사진 다듬기. `PreprocessOptions`로 단계마다 켜고 끔: 영역 자르기 · 크기 · 조명 평탄화 · 기울기 · 이진화 (기본은 크기 · 명암만) |
| `pipeline.py` | 전체 흐름 `run_ocr(사진 바이트) → OcrResult`, 글자 상자를 줄로 묶는 `group_lines` |
| `parser.py` | 줄 → 초안. ① 낱말 위치로 표의 열(단가 · 수량 · 금액) 나누기 ② 규칙(`ParseRules`) ③ 단가×수량 · 품목 합 = 합계로 잘못 읽은 금액 고치기 |
| `bench.py` | 평가 데이터로 점수 매기기. 초안 점수(가게 · 합계 · 품목 F1)와 엔진 점수(파서 없이 본 금액 · 이름 인식률) |
| `ablation.py` | 전처리 단계를 켜고 끄며 점수 비교 (`--grid`: 모든 조합) |
| `synth.py` | 평가용 가짜 영수증 사진 그리기 |
| `samples/` | 평가 데이터: `이름.jpg` + `이름.json`(정답). `dev_`는 규칙 고칠 때 보는 것, `test_`는 처음 보는 것 |
| `../api/v1/ocr.py` | `POST /api/v1/rooms/{room_token}/receipts/{receipt_id}/photo/ocr` (영수증에 올린 사진으로 초안 받기) |

## 설치 (실제 엔진을 쓸 때만)

```powershell
pip install -r requirements-ocr.txt
```
- **Tesseract 프로그램**: Windows는 [UB-Mannheim 설치 파일](https://github.com/UB-Mannheim/tesseract/wiki)에서 설치할 때 Korean 언어를 고릅니다.
  Linux · Docker는 `apt install tesseract-ocr tesseract-ocr-kor`. 다른 경로에 설치했으면 `TESSERACT_CMD`에 exe 경로를 넣습니다.
- **EasyOCR**(비교용): `pip install easyocr`. 처음 쓸 때 한국어 모델을 내려받습니다.
- **Tesseract best 모델**(비교용): [tessdata_best](https://github.com/tesseract-ocr/tessdata_best)의 `kor.traineddata`를
  `kor_best.traineddata`로 이름을 바꿔 Tesseract의 `tessdata` 폴더에 넣고 `--engine tesseract:lang=kor_best`로 씁니다.
- **PaddleOCR**(3회차 비교에서 가장 좋음, 서버 적용 전): numpy · OpenCV 버전이 기존 `.venv`의 패키지와 부딪혀서 **별도 가상환경**에 설치합니다.
  Windows에서 부딪힌 문제 세 가지와 해결:
  - 경로 260자 제한: 깊은 폴더 안에서는 설치가 실패해서 짧은 경로에 만든다.
  - paddlepaddle 3.3.x: CPU 가속(oneDNN)에서 `NotImplementedError`가 나서 3.2.2를 쓴다 (가속을 끄면 장당 약 150초).
  - 사용자 폴더 이름에 한글이 있으면 모델 파일을 못 읽는다: `PADDLE_PDX_CACHE_HOME`을 영문 경로로 지정한다.
  ```powershell
  py -3.12 -m venv $HOME\.venvs\ocr-paddle
  & $HOME\.venvs\ocr-paddle\Scripts\python.exe -m pip install -r requirements.txt Pillow pytesseract paddlepaddle==3.2.2 paddleocr==3.7.0
  $env:PADDLE_PDX_CACHE_HOME = "C:\ProgramData\paddlex"   # 사용자 폴더 경로에 한글이 있을 때만
  & $HOME\.venvs\ocr-paddle\Scripts\python.exe -m app.ocr.bench --engine paddleocr --split dev   # server 폴더에서
  ```
- 서버 기본값은 `OCR_ENGINE=stub`이라 OCR을 설치하지 않은 팀원은 아무것도 하지 않아도 됩니다.

## 써 보기

```powershell
cd server
# 사진 한 장 읽기 (--lines: 줄마다 어떤 역할로 판단했는지)
.venv\Scripts\python -m app.ocr app\ocr\samples\dev_02.jpg --lines
# 전처리 단계를 켜고 단계별 중간 사진 저장 (어느 단계에서 망가졌는지 눈으로 보기)
.venv\Scripts\python -m app.ocr app\ocr\samples\dev_02.jpg --prep crop adaptive_threshold --save-steps steps
# API: 서버를 켜고 /docs 에서 ① POST .../receipts/{receipt_id}/photo 로 사진 올리기 ② POST .../photo/ocr (engine=tesseract)
.venv\Scripts\python -m uvicorn app.main:app --reload

# 채점 (규칙을 고칠 땐 --split dev --show-errors)
.venv\Scripts\python -m app.ocr.bench --engine tesseract easyocr --out results.md
# 전처리 Ablation (dev로 단계를 고르고, test는 고른 설정만 한 번)
.venv\Scripts\python -m app.ocr.ablation --grid
```

## 튜닝하는 곳

| 무엇 | 어디 | 예 |
| --- | --- | --- |
| 무시할 줄 · 합계 · 할인 낱말 | `parser.ParseRules` | `total_keywords`에 '총결제금액' 더하기 |
| 표의 열 이름 | `ParseRules.column_keywords` | 머리줄에 '판매가'를 쓰는 영수증이면 `"unit": ("단가", "판매가")` |
| 숫자 자리 오인식 고치기 | `ParseRules.digit_fixes` | OCR이 5를 S로 읽으면 `"S": "5"` |
| 금액 뒤 과세 표시 | `ParseRules.tax_marks` | 기본 `("T",)` (`32,990 T`). 다른 표시를 찍는 영수증이면 더하기 |
| 사진 키우기 · 명암 · 흑백 | `preprocess.PreprocessOptions` | `min_width=1400`(기본, dev 비교로 정함), `threshold=150` |
| 전처리 단계 켜기 | `PreprocessOptions(crop, target_width, flatten, deskew, adaptive_threshold)` | 2회차 Ablation 결과로 기본은 모두 끔 ([보고서](../../../docs/ocr-report.md)) |
| 엔진 설정 | 명령의 `--engine 이름:설정=값,...` | `tesseract:lang=kor_best`, `easyocr:width_ths=0.1`, `paddleocr:unwarp=true,words=true` |
| 한글 낱말 붙이기 | `engines.join_text(space_ratio=0.65)` | '같 이 고기' → '같이고기' |
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

- 평가 데이터 33장 중 12장이 **가짜 영수증**(`synth.py`)이고 진짜 사진은 21장(dev 14 · test 7)입니다. 가짜가 훨씬 쉬우니 점수는 둘을 나눠서 봅니다(보고서).
- 영역 자르기 · 기울기 보정은 있지만 기본으로 꺼져 있습니다 (진짜 사진 14장으로 비교해도 점수가 오르지 않음, 보고서 2회차). 말린 종이 펴기는 PaddleOCR의 `unwarp` 설정뿐입니다.
- 엔진 비교(보고서 3회차)에서는 PaddleOCR(`paddleocr:unwarp=true` + 최소 전처리)이 가장 좋았지만(진짜 사진 품목 F1 dev 0.72 · test 0.68, Tesseract는 0.44 · 0.42),
  별도 가상환경이 필요해서 서버(`OCR_ENGINE`, API의 `engine`)에는 아직 넣지 않았습니다.
- 품목의 수량은 `lines`에만 있고 초안에는 없습니다 (약속서 품목 칸에 수량이 없어서).
- 요청 안에서 OCR을 기다립니다 (폰 사진 기준 Tesseract 약 1초, PaddleOCR 약 10초). V2에서는 Worker로 옮깁니다.
