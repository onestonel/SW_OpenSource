"""OCR 규칙 파서 · 줄 묶기 · 채점 함수. OCR 엔진 없이 글자 줄만으로 확인한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr.bench import score
from app.ocr.engines import EngineUnavailable, TextBox, get_engine
from app.ocr.parser import Line, parse_receipt
from app.ocr.pipeline import group_lines, run_ocr


def parse(*texts: str):
    return parse_receipt([Line(t) for t in texts])


def test_table_receipt_with_discount():
    r = parse(
        "같이고기 경기대점",
        "사업자번호 123-45-67890 대표 김정산",
        "상품명 단가 수량 금액",
        "삼겹살 16,000 3 48,000",
        "맥주 5,000 2 10,000",
        "합계 58,000",
        "제휴할인 -5,000",
        "결제금액 53,000",
        "부가세 4,818",
        "신용카드 1234-56**-****-7890",
    )
    assert r.draft() == {
        "store_name": "같이고기 경기대점",
        "total_amount": 53000,
        "items": [
            {"name": "삼겹살", "amount": 48000, "kind": "ITEM"},
            {"name": "맥주", "amount": 10000, "kind": "ITEM"},
            {"name": "제휴할인", "amount": -5000, "kind": "DISCOUNT"},
        ],
    }
    assert r.check() == {"items_sum": 53000, "difference": 0, "is_matched": True}
    assert (r.items[0].quantity, r.items[0].unit_price) == (3, 16000)
    assert r.warnings == []


def test_cash_lines_are_not_total():
    # '받은금액'(손님이 낸 돈)은 '받을금액'(낼 돈)과 한 글자 차이지만 합계가 아니다
    r = parse(
        "바삭치킨", "후라이드치킨 1 20,000", "양념치킨 1 21,000", "합계 41,000", "받은금액 50,000", "거스름돈 9,000"
    )
    assert r.total_amount == 41000
    assert [i.amount for i in r.items] == [20000, 21000]


def test_two_line_items_are_merged():
    r = parse("카페 오픈소스", "아메리카노(ICE)", "4,500 x 3 13,500", "카페라떼", "5,000x2 10,000", "받을금액 23,500")
    assert [(i.name, i.amount, i.quantity) for i in r.items] == [("아메리카노(ICE)", 13500, 3), ("카페라떼", 10000, 2)]
    assert r.total_amount == 23500


def test_ocr_noise_in_numbers():
    r = parse("분식집", "떡볶이 2 1O,000", "순대 1 4.500원", "합 계 14,500")
    assert [i.amount for i in r.items] == [10000, 4500]
    assert r.total_amount == 14500


def test_total_inferred_when_keyword_unreadable():
    # '받을금액'을 '23sa4'로 잘못 읽어도, 위 품목 합과 같은 숫자 하나짜리 줄은 합계로 본다
    r = parse("카페", "아메리카노 3 13,500", "카페라떼 2 10,000", "치즈케이크 1 6,500", "23sa4 30,000")
    assert r.total_amount == 30000
    assert len(r.items) == 3
    assert r.check()["is_matched"]


def test_lines_that_look_like_items_are_ignored():
    r = parse(
        "홍콩반점",
        "경기도 수원시 영통구 광교산로 19",  # 주소 (낱말 없이)
        "2026-11-01 13:42",
        "짜장면 2 14,000",
        "합계수량 2",  # 합계 낱말이 있어도 수량
        "합계 14,000",
    )
    assert [i.name for i in r.items] == ["짜장면"]
    assert r.total_amount == 14000


def test_warnings_when_nothing_found():
    r = parse("1234", "")
    assert r.draft() == {"store_name": None, "total_amount": None, "items": []}
    assert len(r.warnings) == 3


def test_mismatch_warning():
    r = parse("가게", "김밥 1 3,000", "라면 1 4,000", "합계 9,000")
    assert r.check() == {"items_sum": 7000, "difference": 2000, "is_matched": False}
    assert "2,000원 다릅니다" in r.warnings[0]


def test_group_lines_by_height():
    boxes = [
        TextBox("48,000", 0.9, 500, 103, 80, 20),  # 오른쪽 금액이 조금 아래 (기울어진 사진)
        TextBox("삼겹살", 0.8, 20, 100, 60, 20),
        TextBox("맥주", 1.0, 20, 140, 40, 20),
        TextBox("10,000", 1.0, 500, 141, 80, 20),
    ]
    assert [ln.text for ln in group_lines(boxes)] == ["삼겹살 48,000", "맥주 10,000"]


def test_score():
    expected = {
        "store_name": "같이고기",
        "total_amount": 15000,
        "items": [
            {"name": "김치찌개", "amount": 10000, "kind": "ITEM"},
            {"name": "공기밥", "amount": 5000, "kind": "ITEM"},
        ],
    }
    draft = {
        "store_name": "같이 고기",
        "total_amount": 15000,
        "items": [
            {"name": "김치찌게", "amount": 10000, "kind": "ITEM"},
            {"name": "콜라", "amount": 2000, "kind": "ITEM"},
        ],
    }
    s = score(expected, draft)
    assert (s["store"], s["total"], s["hit"], s["perfect"]) == (True, True, 1, False)
    assert s["extra"] == [{"name": "콜라", "amount": 2000, "kind": "ITEM"}]


def test_real_engine_on_sample():
    """tesseract가 설치된 컴퓨터에서만: 가짜 영수증 한 장을 끝까지 읽는다."""
    try:
        engine = get_engine("tesseract")
    except EngineUnavailable as e:
        pytest.skip(str(e))
    sample = Path(__file__).parents[1] / "app" / "ocr" / "samples" / "dev_01.jpg"
    result = run_ocr(sample.read_bytes(), engine).receipt
    assert result.total_amount == 40000
    assert result.check()["is_matched"]
