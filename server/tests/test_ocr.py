"""OCR 규칙 파서 · 줄 묶기 · 채점 함수. OCR 엔진 없이 글자 줄만으로 확인한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr.bench import engine_score, partial_similar, score
from app.ocr.engines import EngineUnavailable, TextBox, get_engine, make_engine, parse_settings
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


def test_warehouse_receipt_with_code_lines():
    # 창고형 마트: 이름 줄 + '상품코드 수량 단가 금액 T' 줄. 쿠폰 할인은 금액 뒤 빼기, 품목 중간에 금액 없는 소계 줄
    r = parse(
        "COSTCO",
        "뉴케어구수한맛+",
        "680231 1 32,990 32,990 T",
        "동원 번데기",
        "678820 2 13,990 27,980T",
        "상품수 소계:2",
        "단팥호빵95GX12",
        "577263 1 9,790 9, 790 T",
        "CPN",
        "단팥호빵95GX12",
        "7831 1 1,000 1,000-T",
        "689637 프라이드치킨 1 17,970 17,970 T",
    )
    assert [(i.name, i.amount, i.kind) for i in r.items] == [
        ("뉴케어구수한맛+", 32990, "ITEM"),
        ("동원 번데기", 27980, "ITEM"),
        ("단팥호빵95GX12", 9790, "ITEM"),
        ("단팥호빵95GX12", -1000, "DISCOUNT"),
        ("프라이드치킨", 17970, "ITEM"),
    ]
    assert (r.items[1].quantity, r.items[1].unit_price) == (2, 13990)
    assert r.store_name == "COSTCO"


def test_tax_mark_only_after_amount():
    # 과세 표시 T는 줄 끝 금액 자리에서만 뗀다. 이름 속 T는 그대로
    r = parse("찻집", "얼그레이 T 1 4,500", "합계 4,500")
    assert [(i.name, i.amount) for i in r.items] == [("얼그레이 T", 4500)]


def test_spaced_thousands_without_header():
    r = parse("분식집", "김밥 1 3, 000", "합계 3,000")
    assert [i.amount for i in r.items] == [3000]


def test_name_with_trailing_number_merged_when_next_line_adds_up():
    # 이름 끝 '*10'이 숫자로 읽혀도, 다음 줄이 단가 × 수량 = 금액으로 맞으면 한 품목이다
    r = parse("이마트", "칠성사이다 210ml 10", "8801056095086 5,480 1 5,480", "합계 5,480")
    assert [(i.name, i.amount) for i in r.items] == [("칠성사이다 210ml", 5480)]
    # 산수가 맞지 않는 숫자 줄(날짜 · 번호)은 앞 품목에 붙이지 않는다
    r = parse("분식집", "떡볶이 4,500", "2026 11 24", "합계 4,500")
    assert [(i.name, i.amount) for i in r.items] == [("떡볶이", 4500)]


def test_leading_minus_without_discount_word_is_not_a_discount():
    # 앞에 빼기만 붙은 줄은 할인으로 보지 않는다. 할인으로 넣으면 위 품목 합으로 찾는 소계(13,560)가 깨진다 (보고서 4-1)
    r = parse("농협", "앞다리 1 6,552", "앞다리 1 5,508", "로컬푸드 1 1,500", "(행사) 26년 -300", "총 구 13,560")
    assert [i.amount for i in r.items] == [6552, 5508, 1500]
    assert r.total_amount == 13560


def test_misread_tax_lines_are_not_items():
    # 과세 · 부가세 낱말을 잘못 읽어도('관세 매출' '분가세') 공급가 + 부가세(공급가의 10%) 산수로 세금 줄인 것을 안다
    r = parse("GS25", "마늘빅프랑크 1 2,100", "예거라들러레몬 1 3,300", "관세 매출 4,909", "분가세 491", "합 계 5,400")
    assert [i.name for i in r.items] == ["마늘빅프랑크", "예거라들러레몬"]
    assert r.total_amount == 5400
    assert r.check()["is_matched"]


def test_total_from_tax_lines_when_total_word_unreadable():
    # 합계 낱말을 못 읽으면 면세 + 과세 + 부가세가 합계다. 세금 줄 아래 줄('결제금액'을 잘못 읽은 줄)은 품목이 아니다
    r = parse(
        "이마트", "이맛쌀20kg 1 66,980", "칠성사이다 1 5,480",
        "(*)면세 물품 66,980", "과세 물품 4,982", "부가세 498", "제금 액 5,480",
    )
    assert r.total_amount == 72460
    assert [i.amount for i in r.items] == [66980, 5480]


def test_round_price_lines_are_not_tax_lines():
    # 공급가는 100원 단위로 떨어지지 않는 금액만 본다: 20,000원 + 2,000원은 세금 줄이 아니라 가격 줄이다
    r = parse("치킨집", "후라이드 20,000", "콜라 2,000", "합계 22,000")
    assert [i.amount for i in r.items] == [20000, 2000]


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


def box(text: str, left: int, top: int, width: int) -> TextBox:
    return TextBox(text, 0.9, left, top, width, 20)


def test_table_columns_from_word_positions():
    # 진짜 사진에서 본 모양: 띄어 읽힌 금액('69,' '000'), 열 사이 잡글('ㆍ'), 앞자리를 놓친 단가('000'), 순번('01*')
    lines = group_lines(
        [
            box("상품명", 40, 0, 60), box("단가", 290, 0, 40), box("수량", 400, 0, 40),
            box("금", 520, 0, 20), box("액", 550, 0, 20),  # '금액'이 두 낱말로 쪼개져 읽힘
            box("01*", 0, 30, 30), box("양념갈비", 40, 30, 80), box("ㆍ", 240, 30, 10),
            box("69,", 280, 30, 30), box("000", 315, 30, 30), box("1", 415, 30, 10),
            box("69,", 510, 30, 30), box("000", 545, 30, 30),
            box("된장찌개", 40, 60, 80), box("000", 300, 60, 30), box("2", 415, 60, 10),
            box("6,", 520, 60, 20), box("000", 545, 60, 30),
            box("합계", 40, 90, 40), box("75,000", 510, 90, 60),
        ]
    )  # fmt: skip
    r = parse_receipt(lines)
    assert [(i.name, i.amount, i.quantity, i.unit_price) for i in r.items] == [
        ("양념갈비", 69000, 1, 69000),
        ("된장찌개", 6000, 2, 3000),
    ]
    assert r.total_amount == 75000


def test_amount_column_guessed_when_header_misread():
    # 머리줄의 '금액'을 '글이'로 잘못 읽어도 줄마다 맨 오른쪽 숫자 위치로 금액 열을 정한다
    lines = group_lines(
        [
            box("품명", 40, 0, 40), box("단가", 290, 0, 40), box("수량", 400, 0, 40), box("글이", 530, 0, 40),
            box("김밥", 40, 30, 40), box("3,000", 290, 30, 50), box("2", 415, 30, 10), box("6,000", 520, 30, 50),
            box("합계", 40, 60, 40), box("6,000", 520, 60, 50),
        ]
    )  # fmt: skip
    r = parse_receipt(lines)
    assert [(i.name, i.amount, i.quantity) for i in r.items] == [("김밥", 6000, 2)]
    assert r.total_amount == 6000


def test_far_apart_numbers_in_one_column_are_not_joined():
    # 머리줄의 '수량'을 못 읽으면 수량 '1'이 금액 열로 들어온다. '1' + '3,980' = 13,980으로 잇지 않는다
    lines = group_lines(
        [
            box("상품명", 40, 0, 60), box("단가", 290, 0, 40), box("9장", 400, 0, 40), box("금액", 530, 0, 40),
            box("양파", 40, 30, 40), box("3,980", 285, 30, 50), box("1", 450, 30, 10), box("3,980", 520, 30, 50),
        ]
    )  # fmt: skip
    assert [(i.name, i.amount) for i in parse_receipt(lines).items] == [("양파", 3980)]


def test_misread_amount_fixed_by_arithmetic():
    # 1,580 × 1 ≠ 1,560: 단가로 고치면 품목 합이 합계와 맞으니 금액을 잘못 읽은 것
    r = parse("가게", "상품명 단가 수량 금액", "김밥 1,580 1 1,560", "라면 4,000 1 4,000", "합계 5,580")
    assert [i.amount for i in r.items] == [1580, 4000]
    assert r.check()["is_matched"]
    assert "'김밥' 1,560원 → 1,580원" in r.warnings[0]


def test_arithmetic_keeps_amount_when_total_agrees():
    # 금액끼리 합계와 맞으면 단가를 잘못 읽은 것이라 초안은 그대로, 경고도 없다
    r = parse("가게", "김밥 1,580 1 1,560", "라면 4,000 1 4,000", "합계 5,560")
    assert [i.amount for i in r.items] == [1560, 4000]
    assert r.warnings == []


def test_arithmetic_prefers_fewest_changes():
    # +150은 '쫄면' 하나 또는 '김밥'+'라면' 둘로 맞출 수 있다 → 하나만 고친다
    r = parse("가게", "김밥 1,000 1 900", "라면 2,000 1 1,950", "쫄면 3,000 1 2,850", "합계 5,850")
    assert [i.amount for i in r.items] == [900, 1950, 3000]


def test_arithmetic_warns_when_nothing_fits():
    r = parse("가게", "김밥 1,580 1 1,560", "라면 4,000 1 4,000", "합계 9,999")
    assert [i.amount for i in r.items] == [1560, 4000]
    assert any("단가×수량과 금액이 다른 품목" in w for w in r.warnings)


def test_letter_o_read_as_zero_in_number_columns():
    # EasyOCR은 0을 O로 자주 읽는다: 숫자 열에서는 'OOO' · '0OO'도 숫자로 본다. 이름 칸의 글자는 그대로
    lines = group_lines(
        [
            box("상품명", 40, 0, 60), box("단가", 290, 0, 40), box("수량", 400, 0, 40), box("금액", 530, 0, 40),
            box("SOJU", 40, 30, 60), box("5,", 280, 30, 20), box("0OO", 305, 30, 30), box("1", 415, 30, 10),
            box("5,", 510, 30, 20), box("OOO", 535, 30, 30),
        ]
    )  # fmt: skip
    items = parse_receipt(lines).items
    assert [(i.name, i.amount, i.unit_price) for i in items] == [("SOJU", 5000, 5000)]


def test_engine_score_reads_raw_text_only():
    expected = {
        "items": [
            {"name": "양념갈비1.2kg", "amount": 69000, "kind": "ITEM"},
            {"name": "된장찌개", "amount": 6000, "kind": "ITEM"},
            {"name": "공기밥", "amount": 6000, "kind": "ITEM"},
            {"name": "쿠폰할인", "amount": -3000, "kind": "DISCOUNT"},
        ]
    }
    raw = [
        "양념갈비 1.2kg 69, 000 1 69,000",  # 천 단위 쉼표 옆 띄어쓰기는 붙여서 본다
        "된장찌개 3,000 2 6,000",
        "공 1,000 3 3,000",  # 이름을 못 읽음. 6,000은 위 줄에 한 번뿐이라 두 번째 6,000도 못 맞힘
        "쿠폰할인 -3,000",
        "1,680 1 1,680",  # 칸 사이 띄어쓰기는 붙이지 않는다 (1680116 80이 되면 안 됨)
    ]
    assert engine_score(expected, raw) == {"amount_hit": 3, "name_hit": 3}
    assert engine_score(expected, ["69, OOO"])["amount_hit"] == 0  # O를 0으로 읽은 것은 엔진이 틀린 것


def test_partial_similar_finds_name_inside_line():
    assert partial_similar("된장찌개", "01된장찌개30002") == 1.0
    assert partial_similar("된장찌개", "된장찌게") == 0.75
    assert partial_similar("갈비탕", "칼ㄴ12000") < 0.7


def test_engine_settings_from_command_line():
    assert parse_settings(["crop", "min_width=1", "grayscale=false", "width_ths=0.1", "lang=kor_best"]) == {
        "crop": True,
        "min_width": 1,
        "grayscale": False,
        "width_ths": 0.1,
        "lang": "kor_best",
    }
    assert make_engine("stub").name == "stub"
    with pytest.raises(EngineUnavailable):
        make_engine("없는엔진:x=1")


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


def _png(array) -> bytes:
    import cv2

    return cv2.imencode(".png", array)[1].tobytes()


def _striped_paper(np):
    """흰 종이에 검은 가로줄(글자 줄 흉내) 300x400."""
    paper = np.full((400, 300), 240, np.uint8)
    for y in range(30, 380, 25):
        paper[y : y + 8, 20:280] = 20
    return paper


def test_crop_straightens_receipt_on_desk():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from app.ocr.preprocess import PreprocessOptions, preprocess

    desk = np.full((800, 600), 60, np.uint8)
    desk[200:600, 150:450] = _striped_paper(np)
    tilted = cv2.warpAffine(desk, cv2.getRotationMatrix2D((300, 400), 4, 1.0), (600, 800), borderValue=60)
    opts = PreprocessOptions(crop=True, min_width=10, max_width=5000, autocontrast=False)
    img, notes = preprocess(_png(tilted), opts)
    assert notes == []
    assert abs(img.width - 300) < 20 and abs(img.height - 400) < 20  # 책상은 빠지고 종이만 남는다
    assert np.array(img).mean() > 150  # 종이 안쪽(밝음)만 남았다


def test_crop_reports_when_no_receipt():
    np = pytest.importorskip("numpy")
    from app.ocr.preprocess import PreprocessOptions, preprocess

    dark = np.full((400, 300), 40, np.uint8)
    dark[10:30, 10:30] = 250  # 종이라기엔 너무 작은 밝은 곳
    _, notes = preprocess(_png(dark), PreprocessOptions(crop=True))
    assert notes == ["영수증 영역을 찾지 못해 사진 전체를 읽었습니다."]


def test_deskew_levels_text_lines():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from app.ocr.preprocess import PreprocessOptions, preprocess

    paper = _striped_paper(np)
    tilted = cv2.warpAffine(paper, cv2.getRotationMatrix2D((150, 200), 3, 1.0), (300, 400), borderValue=240)
    opts = PreprocessOptions(deskew=True, min_width=10, max_width=5000, autocontrast=False)
    img, _ = preprocess(_png(tilted), opts)
    rows = np.array(img)[:, 60:240].mean(axis=1)
    # 줄이 수평이면 한 행이 통째로 검거나 희다. 기울어 있으면 회색 행(반쯤 검은 행)이 많다
    half = ((rows > 60) & (rows < 200)).sum()
    before = np.array(tilted)[:, 60:240].mean(axis=1)
    assert half < ((before > 60) & (before < 200)).sum() / 2
