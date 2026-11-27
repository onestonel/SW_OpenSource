"""OCR 결과 → 영수증 초안 값 정리 (app/ocr_draft.py). 고친 값이 영수증 입력 규칙을 통과하는지까지 확인한다."""

from __future__ import annotations

import pytest

from app.ocr_draft import RawDraft, RawLine, make_draft, parse_amount


def ocr(store="1차 식당", total="31,000", lines=(("김치찌개", "9,000"), ("삼겹살", "24,000원"), ("할인", "-2,000"))):
    return RawDraft(store_name=store, total_amount=total, lines=[RawLine(*line) for line in lines])


def rows(draft) -> list[tuple[str, int, str]]:
    return [(i.name, i.amount, i.kind) for i in draft.items]


@pytest.mark.parametrize("value, expected", [
    (12000, 12000), (12000.0, 12000), ("12000", 12000), ("12,000", 12000), ("12.000", 12000),
    ("12,000원", 12000), ("₩12,000", 12000), (" 1 2,000 ", 12000), ("-3,000", -3000), ("−3,000", -3000),
    ("1,234,567", 1234567),
    (None, None), (True, None), (12.5, None), ("", None), ("abc", None), ("12,00", None), ("12,000.5", None),
])
def test_parse_amount(value, expected):
    assert parse_amount(value) == expected


def test_clean_receipt_has_no_notes():
    d = make_draft(ocr())
    assert d.ok and d.notes == []
    assert d.store_name == "1차 식당" and d.total_amount == 31000
    assert rows(d) == [("김치찌개", 9000, "ITEM"), ("삼겹살", 24000, "ITEM"), ("할인", -2000, "DISCOUNT")]


def test_discount_word_with_plus_amount_becomes_minus():
    d = make_draft(ocr(total="7,000", lines=[("아메리카노", "8,000"), ("쿠폰 할인", "1,000")]))
    assert rows(d) == [("아메리카노", 8000, "ITEM"), ("쿠폰 할인", -1000, "DISCOUNT")]
    assert d.notes == ["'쿠폰 할인': 할인으로 보고 -1,000원으로 넣었습니다."]


def test_unreadable_zero_and_huge_amounts_are_dropped():
    d = make_draft(ocr(total="5,000", lines=[("콜라", None), ("물", "0"), ("사이다", "1,000,000,000"),
                                             ("과자", "5,000"), ("영수증번호", "A-12")]))
    assert rows(d) == [("과자", 5000, "ITEM")]
    assert d.notes == [
        "'콜라': 금액을 읽지 못해 뺐습니다.",
        "'물': 0원이라 뺐습니다.",
        "'사이다': 금액(1,000,000,000원)이 1억 원을 넘어 잘못 읽은 것으로 보고 뺐습니다.",
        "'영수증번호': 금액을 읽지 못해 뺐습니다.",
    ]


def test_missing_and_long_names_are_fixed():
    long_name = "아주 " * 30
    d = make_draft(ocr(store="  ", total="6,000", lines=[(None, "3,000"), ("", "-1,000"), (long_name, "4,000")]))
    assert d.store_name == "영수증"
    assert [i.name for i in d.items] == ["품목 1", "할인", " ".join(long_name.split())[:50]]
    assert all(len(i.name) <= 50 for i in d.items)
    assert d.notes[:3] == [
        "1번째 줄: 이름을 읽지 못해 '품목 1'(으)로 넣었습니다.",
        "2번째 줄: 이름을 읽지 못해 '할인'(으)로 넣었습니다.",
        f"'{d.items[2].name}': 이름이 길어 앞 50자만 넣었습니다.",
    ]
    assert "가게 이름을 읽지 못해 '영수증'(으)로 넣었습니다." in d.notes


def test_missing_total_uses_items_sum_with_discount():
    d = make_draft(ocr(total=None))
    assert d.total_amount == 31000
    assert d.notes == ["합계를 읽지 못해 품목 합(31,000원)으로 넣었습니다."]


def test_wrong_total_is_kept():
    d = make_draft(ocr(total="33,000"))
    assert d.total_amount == 33000  # 합계를 품목 합으로 바꾸지 않는다 (어느 쪽이 틀렸는지 모른다)
    assert d.notes == []  # 합계 ≠ 품목 합은 OCR 경고와 영수증 check가 이미 알려 준다


def test_negative_total_uses_items_sum():
    d = make_draft(ocr(total="-31,000"))
    assert d.total_amount == 31000
    assert d.notes == ["합계(-31,000원)가 올바르지 않아 품목 합(31,000원)으로 넣었습니다."]


def test_no_items_is_not_ok():
    d = make_draft(ocr(total=None, lines=[("할인", "-1,000"), ("합계", "abc")]))
    assert not d.ok and d.total_amount is None
    assert d.problem == "품목을 하나도 읽지 못해"
    with pytest.raises(ValueError, match="품목을 하나도 읽지 못해 영수증을 만들 수 없습니다"):
        d.to_receipt_in(payer_member_id=1)


def test_no_total_and_no_plus_sum_is_not_ok():
    d = make_draft(ocr(total=None, lines=[("물", "1,000"), ("할인", "-2,000")]))
    assert d.total_amount is None and d.problem == "총액을 정하지 못해"


def test_kind_from_ocr_is_followed():
    """OCR이 정한 줄 종류를 따른다. '할인상품'이라는 낱말이 있어도 ITEM이면 품목이다."""
    d = make_draft(ocr(total="9,000", lines=[("할인상품 우유", "3,000", "ITEM"), ("제휴", "1,000", "DISCOUNT"),
                                             ("빵", "7,000", None)]))
    assert rows(d) == [("할인상품 우유", 3000, "ITEM"), ("제휴", -1000, "DISCOUNT"), ("빵", 7000, "ITEM")]
    assert d.notes == ["'제휴': 할인으로 보고 -1,000원으로 넣었습니다."]


@pytest.mark.parametrize("ocr_store", ["같이고기 경기대점", None, "  ", "가" * 60])
def test_given_store_name_is_used_as_is(ocr_store):
    """사용자가 적은 가게 이름을 주면 OCR이 읽은 가게 이름은 쓰지 않고, 가게 이름 알림도 남기지 않는다."""
    d = make_draft(ocr(store=ocr_store), store_name="1차 식당")
    assert d.store_name == "1차 식당"
    assert d.notes == []


def test_more_than_100_lines_keeps_first_100():
    d = make_draft(ocr(total=None, lines=[(f"품목{n}", "1,000") for n in range(1, 106)]))
    assert len(d.items) == 100 and d.items[-1].name == "품목100"
    assert d.total_amount == 100_000
    assert d.notes[0] == "줄이 105개라 앞의 100개만 넣었습니다."


def test_from_dict():
    """OCR API 답장의 draft 모양 그대로 받는다 (store_name · total_amount는 null일 수 있다)."""
    r = RawDraft.from_dict({"store_name": None, "total_amount": None,
                            "items": [{"name": "우유", "amount": 3000, "kind": "ITEM"},
                                      {"name": "쿠폰", "amount": -500, "kind": "DISCOUNT"}]})
    d = make_draft(r)
    assert rows(d) == [("우유", 3000, "ITEM"), ("쿠폰", -500, "DISCOUNT")]
    assert d.store_name == "영수증" and d.total_amount == 2500
    assert RawDraft.from_dict({}).lines == []


def test_draft_is_saved_as_checking_receipt(api):
    """정리한 초안은 영수증 만들기 규칙을 통과하고, '확인 중' 영수증으로 저장된다."""
    room = api.post("/rooms", {"name": "제주 여행", "members": ["A", "B"]}).json()
    payer = room["members"][0]["id"]
    d = make_draft(ocr(store="가" * 60, total="33,000", lines=[("김치찌개", "9,000"), (None, "24,000"),
                                                                 ("쿠폰", "2,000"), ("물", "0")]))
    body = d.to_receipt_in(payer).model_dump(exclude_none=True)
    r = api.post(f"/rooms/{room['room_token']}/receipts", body).json()
    assert r["status"] == "CHECKING" and r["store_name"] == "가" * 50
    assert [(i["name"], i["amount"], i["kind"]) for i in r["items"]] == [
        ("김치찌개", 9000, "ITEM"), ("품목 2", 24000, "ITEM"), ("쿠폰", -2000, "DISCOUNT")]
    assert r["check"] == {"items_sum": 31000, "difference": 2000, "is_matched": False}
