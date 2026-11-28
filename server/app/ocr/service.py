"""ocr 컨테이너 안에서 도는 OCR 서버 (docker compose --profile ocr).

PaddleOCR은 서버(app.main)의 패키지와 numpy · OpenCV 버전이 부딪혀서 이 컨테이너에서 따로 돈다.
서버(OCR_ENGINE=remote)가 사진 바이트를 POST /ocr로 보내면, run_ocr 결과를 서버의 사진 인식 API와
같은 모양(OcrResult.to_dict)으로 돌려준다.

    uvicorn app.ocr.service:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .engines import PaddleOcrEngine
from .pipeline import run_ocr
from .preprocess import ImageUnreadable, PreprocessOptions

# 보고서 6회차에서 가장 좋았던 설정 (문서 펴기 + 최소 전처리).
# 모델은 켤 때 불러온다 (처음에는 내려받느라 몇 분). 그동안은 포트가 열리지 않아 서버가 503으로 알린다
ENGINE = PaddleOcrEngine(unwarp=True)
PREP = PreprocessOptions(grayscale=False, min_width=1, max_width=10000, autocontrast=False)

app = FastAPI(title="같이정산 OCR")


@app.post("/ocr")
async def ocr(request: Request) -> dict:
    # async 안에서 바로 돌려 한 번에 한 장씩 읽는다 (엔진 하나를 여러 스레드가 같이 쓰지 않게)
    try:
        return run_ocr(await request.body(), ENGINE, prep=PREP).to_dict()
    except ImageUnreadable as e:
        raise HTTPException(422, str(e)) from e
