"""영수증 사진 → 영수증 초안 (V2 자동 인식 프로토타입). 구조와 튜닝 방법은 같은 폴더의 README.md."""

from .pipeline import OcrResult, run_ocr

__all__ = ["OcrResult", "run_ocr"]
