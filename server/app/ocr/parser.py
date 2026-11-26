"""글자 줄 → 영수증 초안 (규칙 기반).

판단 기준(낱말 · 숫자 범위)은 전부 ParseRules 한 곳에 모았다. 새 모양의 영수증을 잘못 읽으면
여기 낱말을 더하고 `python -m app.ocr.bench`로 점수가 오르는지 확인한다.

규칙보다 먼저 두 가지를 한다 (가게마다 다른 낱말이 아니라 모든 영수증에 통하는 구조를 쓴다).
- 표 읽기(_read_columns): 낱말 위치가 있으면 머리줄의 '단가 · 수량 · 금액' x 위치로 열을 나눈다.
  '69, 000'처럼 띄어 읽힌 숫자는 같은 열이라 이어 붙고, 열 사이의 잡글('_', 'ㆍ')은 버려진다.
- 산수 검산(_reconcile): 단가×수량 ≠ 금액인 품목은 둘 중 하나를 잘못 읽은 것이다. 품목 합 = 합계가 되는 쪽을 고른다.
나중에 LLM으로 바꾸고 싶으면 parse_receipt와 같은 모양(줄 목록 → ParsedReceipt)의 함수를 만들면 된다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import combinations
from statistics import median

from .engines import TextBox, join_text

ITEM, DISCOUNT = "ITEM", "DISCOUNT"


@dataclass(frozen=True)
class ParseRules:
    """영수증을 읽는 규칙. 값을 바꿔 가며 bench 점수를 비교하는 곳."""

    # 이 낱말이 든 줄은 가게 이름 · 품목 · 합계 어디에도 쓰지 않는다
    ignore_keywords: tuple[str, ...] = (
        "사업자",
        "대표",
        "주소",
        "전화",
        "TEL",
        "일시",
        "날짜",
        "거래",
        "테이블",
        "주문",
        "번호",
        "POS",
        "영수증",
        "고객용",
        "부가세",
        "부가가치세",
        "과세",
        "면세",
        "공급가",
        "VAT",
        "카드",
        "승인",
        "할부",
        "단말기",
        "받은금액",
        "받은돈",
        "거스름",
        "잔돈",
        "현금",
        "포인트",
        "적립",
        "감사합니다",
        "서명",
        "교환",
        "환불",
    )
    # 이 모양(정규식, 띄어쓰기를 뺀 글자에 적용)이 있는 줄도 쓰지 않는다: 주소 · 날짜 · 시각 · 전화번호
    ignore_patterns: tuple[str, ...] = (
        r"(시|군|구)\S*?(로|길)\d",
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{1,2}:\d{2}",
        r"\d{2,4}-\d{3,4}-\d{4}",
    )
    # 가게 이름이 이 낱말 뒤에 오는 영수증 (상호: OO식당)
    store_keywords: tuple[str, ...] = ("상호", "매장명", "가맹점명", "점포명")
    # 품목 표의 머리줄. 이 낱말이 2개 이상 있고 숫자가 없는 줄 아래부터 품목으로 본다
    header_keywords: tuple[str, ...] = ("상품명", "품명", "메뉴", "품목", "단가", "수량", "금액")
    # 머리줄에서 열 위치를 잡는 낱말 (낱말 위치를 주는 엔진에서만 쓴다)
    column_keywords: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {"unit": ("단가",), "qty": ("수량",), "amount": ("금액",)}
    )
    # 합계 낱말. 앞 묶음일수록 우선한다 (할인 뒤 실제 낸 돈 > 할인 전 합계 > 소계)
    total_keywords: tuple[tuple[str, ...], ...] = (
        ("결제금액", "받을금액", "청구금액", "총결제", "결제합계"),
        ("합계", "총액", "총금액", "TOTAL"),
        ("소계",),
    )
    # 합계 낱말이 있어도 금액이 아닌 줄 (합계수량 12 → 12원이 아님)
    total_exclude_keywords: tuple[str, ...] = ("수량", "건수", "개수")
    discount_keywords: tuple[str, ...] = ("할인", "DC", "쿠폰", "에누리")
    # 금액 뒤에 찍는 과세 표시 ('32,990 T' '27,980T'). 줄 끝 금액 자리에서만 뗀다. 창고형 마트 형식 (4회차)
    tax_marks: tuple[str, ...] = ("T",)
    # 면세 물품 금액 줄. 세금 줄(공급가 + 부가세) 바로 위에 있으면 그 금액도 세금 합에 더한다 (면세 + 과세 + 부가세 = 합계)
    tax_free_keywords: tuple[str, ...] = ("면세",)
    # 세금 줄 낱말. 반복 금액으로 합계를 찾을 때 세지 않는다 (면세물품가액 줄은 할인 전 금액이 한 번 더 찍힌 것이라)
    tax_keywords: tuple[str, ...] = ("부가세", "부가가치세", "과세", "면세", "공급가", "VAT")
    # 숫자 자리에 자주 섞여 들어오는 비슷한 글자 (OCR이 0을 O로 읽는 등). 숫자가 반 이상인 낱말에만 쓴다
    digit_fixes: dict[str, str] = field(
        default_factory=lambda: {
            "O": "0",
            "o": "0",
            "D": "0",
            "Q": "0",
            "l": "1",
            "I": "1",
            "!": "1",
            "S": "5",
            "B": "8",
        }
    )
    max_quantity: int = 99
    min_amount: int = 10
    max_amount: int = 10_000_000
    # OCR 확신도가 이보다 낮은 줄이 품목 · 합계에 쓰이면 경고한다
    low_confidence: float = 0.6


@dataclass(frozen=True)
class Line:
    """글자 한 줄과 OCR 확신도(0~1).

    boxes: 엔진이 준 상자(위치). 비어 있으면(글자만 넣은 테스트 등) 표 읽기를 건너뛴다.
    cells: 표 읽기로 나눈 (이름, 단가, 수량, 금액). 있으면 text를 다시 쪼개지 않고 이것을 쓴다.
    """

    text: str
    conf: float = 1.0
    boxes: tuple[TextBox, ...] = ()
    cells: tuple[str, int | None, int | None, int] | None = None


@dataclass
class ParsedItem:
    name: str
    amount: int
    kind: str = ITEM
    quantity: int | None = None
    unit_price: int | None = None


@dataclass
class ParsedLine:
    """줄마다 어떤 역할로 판단했는지. 잘못 읽었을 때 원인을 찾는 데 쓴다."""

    text: str
    conf: float
    role: str  # store · header · item · discount · total · subtotal · ignored · other


@dataclass
class ParsedReceipt:
    store_name: str | None
    total_amount: int | None
    items: list[ParsedItem]
    lines: list[ParsedLine]
    warnings: list[str]

    @property
    def items_sum(self) -> int:
        return sum(i.amount for i in self.items)

    def check(self) -> dict:
        """API 약속서의 영수증 check와 같은 계산: difference = total_amount − items_sum."""
        diff = None if self.total_amount is None else self.total_amount - self.items_sum
        return {"items_sum": self.items_sum, "difference": diff, "is_matched": diff == 0}

    def draft(self) -> dict:
        """API 약속서 '영수증 만들기'에 보낼 칸과 같은 모양 (payer_member_id는 사람이 고른다)."""
        return {
            "store_name": self.store_name,
            "total_amount": self.total_amount,
            "items": [{"name": i.name, "amount": i.amount, "kind": i.kind} for i in self.items],
        }


_NUM = re.compile(r"[-−–]?(?:\d{1,3}(?:[,.]\d{3})+|\d+)")
_LETTER = re.compile(r"[가-힣A-Za-z]")
_TIMES = re.compile(r"(\d)\s*[xX×*]\s*(\d)")
# 쉼표 뒤에 띄어쓰기가 끼어 읽힌 천 단위 ('9, 790' → '9,790'). 머리줄이 있으면 표 읽기가 잇지만, 없는 영수증도 있다
_SPACED_THOUSANDS = re.compile(r"(?<=\d),\s+(?=\d{3}(?!\d))")
_SKIP_TOKENS = {"x", "X", "×", "*", "@", "=", "|"}
_NAME_STRIP = " :：·-=|[]【】<>'\"`ㆍ、.,*_"  # 괄호 ()는 '탕수육(소)'처럼 이름의 일부라 남긴다
_INDEX = re.compile(r"^\d{1,3}[*._,)\]]*\s+")  # 이름 앞의 순번 '01 ' '08*. ' '12__ '
# 이름 앞의 상품코드 '689637 프라이드치킨' (창고형 마트 형식). 4자리 이하는 '2080 치약' 같은 상표일 수 있어 남긴다
_CODE = re.compile(r"^\d{5,}\s+")


def _clean_name(name: str) -> str:
    return _CODE.sub("", _INDEX.sub("", name.strip(_NAME_STRIP))).strip(_NAME_STRIP)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def _has(text: str, keywords) -> bool:
    """줄에 낱말이 있는지. 한글은 띄어쓰기를 무시하고('합 계' = '합계'), 영어는 낱말 단위로 본다('HOTEL' ≠ 'TEL')."""
    compact, upper = _compact(text), text.upper()
    for kw in keywords:
        if kw.isascii():
            if re.search(rf"(?<![A-Z]){re.escape(kw.upper())}(?![A-Z])", upper):
                return True
        elif kw in compact:
            return True
    return False


def _normalize(text: str) -> str:
    text = _TIMES.sub(r"\1 \2", text)  # '4,500x3' → '4,500 3'
    text = _SPACED_THOUSANDS.sub(",", text)
    return re.sub(r"\s+", " ", text).strip()


def _fix_digits(token: str, fixes: dict[str, str]) -> str:
    """숫자 칸에 섞인 비슷한 글자를 고친다 ('1O,000' → '10,000')."""
    core = token.strip(",.원-")
    digits = sum(c.isdigit() for c in core)
    if digits == 0 or digits * 2 < len(core):
        return token
    return "".join(fixes.get(c, c) for c in token)


def _number(token: str, rules: ParseRules) -> int | None:
    """낱말이 숫자면 정수로. '10,000원' '-5,000' '10.000' 모두 된다. '2L' '1.25L' 같은 이름 조각은 None."""
    t = _fix_digits(token, rules.digit_fixes).removesuffix("원").strip(".,'\"`")
    if not _NUM.fullmatch(t):
        return None
    sign = -1 if t[0] in "-−–" else 1
    return sign * int(re.sub(r"\D", "", t))


def _strip_tax_mark(token: str, rules: ParseRules) -> str:
    """금액 바로 뒤에 붙은 과세 표시를 뗀다 ('22,990T' → '22,990', '1,000-T' → '1,000-')."""
    for mark in rules.tax_marks:
        head = token.removesuffix(mark)
        if head != token and head and (head[-1].isdigit() or head[-1] in "-−–"):
            return head
    return token


_MINUS_AFTER = re.compile(r"^(\d[\d,.]*)[-−–]$")  # 금액 뒤에 붙은 빼기 '1,000-' (창고형 마트의 할인 표기)


def _last_amount_token(text: str, rules: ParseRules) -> str:
    """줄 끝의 금액 낱말 (뒤에 따로 찍힌 과세 표시는 건너뛰고, 붙은 것은 뗀다)."""
    tokens = text.split()
    while tokens and tokens[-1] in rules.tax_marks:
        tokens.pop()
    return _strip_tax_mark(tokens[-1], rules) if tokens else ""


def _minus_after_amount(text: str, rules: ParseRules) -> bool:
    return bool(_MINUS_AFTER.match(_last_amount_token(text, rules)))


def _split(text: str, rules: ParseRules) -> tuple[str, list[int]]:
    """줄을 '이름 부분'과 '끝에 붙은 숫자들'로 나눈다. '김치찌개 9,000 2 18,000' → ('김치찌개', [9000, 2, 18000])"""
    tokens = _normalize(text).split()
    nums: list[int] = []
    while tokens:
        tok = tokens[-1]
        if tok in _SKIP_TOKENS or (not nums and tok in rules.tax_marks):
            tokens.pop()
            continue
        if not nums:  # 줄 끝 금액 자리: 과세 표시를 떼고, 뒤에 붙은 빼기는 앞으로 ('1,000-T' → '-1,000')
            tok = _MINUS_AFTER.sub(r"-\1", _strip_tax_mark(tok, rules))
        n = _number(tok, rules)
        if n is None:
            break
        nums.insert(0, n)
        tokens.pop()
    # 이름 중간에 큰 숫자가 끼면(숫자를 글자로 잘못 읽어 끝 숫자가 끊긴 경우) 그 앞까지만 이름으로 본다
    for k in range(1, len(tokens)):
        n = _number(tokens[k], rules)
        if n is not None and abs(n) >= 100:
            tokens = tokens[:k]
            break
    return _clean_name(" ".join(tokens)), nums


def _quantity(nums: list[int], rules: ParseRules) -> tuple[int | None, int | None]:
    """끝 숫자들에서 (수량, 단가)를 추정한다. 마지막 숫자는 언제나 금액."""
    amount = nums[-1]
    if len(nums) >= 3:
        a, b = nums[-3], nums[-2]
        if a * b == amount:
            return (b, a) if b <= rules.max_quantity else (a, b)
        return (b if 0 < b <= rules.max_quantity else None), a
    if len(nums) == 2:
        a = nums[0]
        if 0 < a <= rules.max_quantity:
            return a, (amount // a if amount % a == 0 else None)
        if a > 0 and amount % a == 0 and amount // a <= rules.max_quantity:
            return amount // a, a
    return None, None


def _is_header(text: str, nums: list[int], rules: ParseRules) -> bool:
    compact = _compact(text)
    return not nums and sum(kw in compact for kw in rules.header_keywords) >= 2


def _priced(nums: list[int]) -> bool:
    """끝의 세 숫자가 단가 × 수량 = 금액으로 맞는지 (순서는 어느 쪽이든)."""
    return len(nums) >= 3 and nums[-3] * nums[-2] == abs(nums[-1])


def _merge_two_line_items(lines: list[Line], rules: ParseRules) -> list[Line]:
    """'이름만 있는 줄' 다음에 '숫자만 있는 줄'이 오면 한 줄로 합친다 (메뉴 이름을 따로 찍는 영수증).

    이름 끝이 숫자로 읽힌 줄('칠성사이다 210ml 10')도 다음 줄이 단가 × 수량 = 금액으로 맞는 숫자 줄이면 합친다.
    """
    out: list[Line] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i + 1 < len(lines):
            name, nums = _split(cur.text, rules)
            next_name, next_nums = _split(lines[i + 1].text, rules)
            if (
                name
                and (not nums or (len(nums) == 1 and _priced(next_nums)))
                and next_nums
                and not _LETTER.search(next_name)
                and not _has(cur.text, rules.ignore_keywords)
                and not _is_header(cur.text, nums, rules)
            ):
                out.append(Line(f"{cur.text} {lines[i + 1].text}", min(cur.conf, lines[i + 1].conf)))
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


def _clean_store(text: str, rules: ParseRules) -> str:
    for kw in rules.store_keywords:
        if kw in text:
            text = text.split(kw, 1)[1]
            break
    for kw in rules.ignore_keywords:  # '상호: 같이고기 대표: 김정산' → '같이고기'
        if not kw.isascii() and kw in text:
            text = text.split(kw, 1)[0]
    return re.sub(r"\s+", " ", text).strip(_NAME_STRIP)


def _words(boxes: tuple[TextBox, ...]) -> list[TextBox]:
    """상자를 띄어쓰기 단위 낱말 상자로 쪼갠다. 여러 낱말이 든 상자(줄 단위 엔진)는 글자 수 비율로 위치를 나눈다."""
    out = []
    for b in boxes:
        n = max(len(b.text), 1)
        for m in re.finditer(r"\S+", b.text):
            left = b.left + b.width * m.start() / n
            out.append(TextBox(m.group(), b.conf, round(left), b.top, round(b.width * len(m.group()) / n), b.height))
    return sorted(out, key=lambda w: w.left)


def _center(box: TextBox) -> float:
    return box.left + box.width / 2


def _find_columns(header: Line, rules: ParseRules) -> tuple[float, dict[str, float]] | None:
    """머리줄에서 (이름 칸의 오른쪽 경계, {열: 가운데 x})를 찾는다. '금 액'처럼 쪼개 읽혀도 찾도록 글자 단위로 본다."""
    chars: list[tuple[str, float, float]] = []  # 글자, 가운데 x, 글자 폭
    for w in _words(header.boxes):
        cw = w.width / len(w.text)
        chars += [(c, w.left + cw * (k + 0.5), cw) for k, c in enumerate(w.text)]
    joined = "".join(c for c, _, _ in chars)
    centers, starts = {}, []
    for kind, keywords in rules.column_keywords.items():
        for kw in keywords:
            at = joined.find(kw)
            if at >= 0:
                span = chars[at : at + len(kw)]
                centers[kind] = sum(x for _, x, _ in span) / len(span)
                starts.append(span[0][1] - span[0][2] / 2)
                break
    if not centers:
        return None
    return min(starts), centers


def _column_digits(token: str, fixes: dict[str, str]) -> str:
    """숫자 열 안의 낱말은 숫자처럼 생긴 글자만으로 되어 있으면 숫자로 읽는다 ('OOO' → '000', 'S,OOO' → '5,000').

    _fix_digits는 이름에도 쓰여서 숫자가 반 이상인 낱말만 고치지만, 숫자 열에서는 글자일 이유가 없다
    (EasyOCR은 0을 O로 자주 읽는다). 한 글자짜리('B', 'I')는 표의 선 · 잡글일 수 있어 고치지 않는다.
    """
    looks_numeric = all(c.isdigit() or c in fixes or c in ",.-−–" for c in token)
    if looks_numeric and (len(token) >= 2 or token.isdigit()):
        return "".join(fixes.get(c, c) for c in token)
    return token


def _cell(words: list[TextBox], center: float, rules: ParseRules, signed: bool = False) -> int | None:
    """한 열에 든 낱말들 → 숫자. 띄어 읽힌 조각('69,' '000')은 잇고, 숫자 아닌 잡글은 버린다.

    간격이 글자 높이보다 넓게 떨어진 덩어리는 다른 칸의 숫자다 (머리줄에서 '수량'을 못 읽으면 수량 '1'이
    금액 열에 들어와 '1' + '3,980' = 13,980이 된다). 그래서 열 가운데에 가장 가까운 덩어리 하나만 쓴다.
    """
    words = [replace(w, text=_column_digits(w.text, rules.digit_fixes)) for w in words]
    groups: list[list[TextBox]] = []
    for w in words:
        if groups and w.left - (groups[-1][-1].left + groups[-1][-1].width) <= w.height * 0.8:
            groups[-1].append(w)
        else:
            groups.append([w])
    groups = [g for g in groups if re.search(r"\d", "".join(w.text for w in g))]
    if not groups:
        return None
    nearest = min(groups, key=lambda g: abs((g[0].left + g[-1].left + g[-1].width) / 2 - center))
    text = "".join(_fix_digits(w.text, rules.digit_fixes) for w in nearest)
    digits = re.sub(r"\D", "", text)
    if not digits or int(digits) == 0:  # '000'만 읽힌 칸(앞자리를 놓침)은 없는 것으로 본다
        return None
    sign = -1 if signed and re.match(r"\D*?[-−–]\d", text) else 1
    return sign * int(digits)


def _read_columns(lines: list[Line], rules: ParseRules) -> list[Line]:
    """머리줄 아래 줄을 낱말 위치로 (이름, 단가, 수량, 금액) 칸에 나눈다. 머리줄이나 위치가 없으면 그대로 돌려준다."""
    header_idx = next(
        (i for i, ln in enumerate(lines) if ln.boxes and _is_header(ln.text, _split(ln.text, rules)[1], rules)), None
    )
    found = _find_columns(lines[header_idx], rules) if header_idx is not None else None
    if found is None:
        return lines
    name_edge, centers = found
    rows = [(i, _words(ln.boxes)) for i, ln in enumerate(lines) if i > header_idx and ln.boxes]
    if "amount" not in centers:
        # 머리줄의 '금액'을 못 읽었으면, 기존 열보다 오른쪽에 있는 '줄마다 맨 오른쪽 숫자'의 가운데로 정한다
        last = max(centers.values())
        xs = [_center(w[-1]) for _, w in rows if w and re.search(r"\d", w[-1].text) and _center(w[-1]) > last]
        if not xs:
            return lines
        centers["amount"] = median(xs)

    out = list(lines)
    for i, words in rows:
        text = lines[i].text
        if _has(text, rules.ignore_keywords) or any(re.search(p, _compact(text)) for p in rules.ignore_patterns):
            continue
        name_words, cols = [], {kind: [] for kind in centers}
        for w in words:
            if _center(w) < name_edge:
                name_words.append(w)
            else:
                cols[min(centers, key=lambda k: abs(centers[k] - _center(w)))].append(w)
        cell = {kind: _cell(cols[kind], centers[kind], rules, signed=kind == "amount") for kind in centers}
        amount, unit, qty = cell["amount"], cell.get("unit"), cell.get("qty")
        if amount is None:
            continue  # 금액 칸이 비면 품목 줄이 아니다 (글자만 있는 줄 · 이름이 두 줄인 품목의 첫 줄)
        if qty is not None and qty > rules.max_quantity:
            qty = None
        name = _clean_name(join_text(name_words))
        shown = " ".join([name] + [f"{n:,}" for n in (unit, qty, amount) if n is not None])
        out[i] = replace(lines[i], text=shown, cells=(name, unit, qty, amount))
    return out


def _tax_lines(
    lines: list[Line], split: list[tuple[str, list[int]]], roles: list[str], rules: ParseRules
) -> tuple[list[int], int | None]:
    """공급가 + 부가세(공급가의 10% ± 1원) 짝 줄을 산수로 찾는다. (세금 줄 번호들, 세금 합)

    낱말을 잘못 읽어도('관세 매출 6,436' + '분가세 644') 찾을 수 있다. 가격 줄과 헷갈리지 않게 공급가는 100원 단위로
    떨어지지 않는 금액만 본다 (공급가 = 합계 ÷ 1.1이라 대개 끝자리가 남는다. 20,000원 + 2,000원 같은 가격 줄은 거른다).
    """
    for i, (_, nums) in enumerate(split):
        if roles[i] == "header" or len(nums) != 1 or nums[0] <= 0 or nums[0] % 100 == 0:
            continue
        supply = nums[0]
        for j in range(i + 1, min(i + 3, len(lines))):
            vat = split[j][1]
            if len(vat) == 1 and vat[0] >= rules.min_amount and abs(vat[0] * 10 - supply) <= 10:
                block, total = [i, j], supply + vat[0]
                for k in range(i - 1, max(i - 4, -1), -1):  # 면세 줄은 과세 줄 바로 위에 찍힌다
                    if split[k][1] and _has(lines[k].text, rules.tax_free_keywords):
                        block.append(k)
                        total += split[k][1][-1]
                        break
                return sorted(block), total
    return [], None


def _repeated_total(
    lines: list[Line],
    split: list[tuple[str, list[int]]],
    found: list[tuple[int, ParsedItem]],
    start: int,
    tax_idx: list[int],
    rules: ParseRules,
) -> tuple[int, int, int] | None:
    """결제 줄에 두 번 이상 찍힌 금액으로 합계를 찾는다. (합계, 그 금액이 처음 맞는 줄, 반영한 할인)

    합계 · 받을금액 · 카드 결제 줄은 같은 금액을 되풀이한다. 그런 금액 중 그 줄 위의 품목 합(또는 품목 합 - 그 위에
    찍힌 빼기 금액 하나)과 맞는 가장 큰 것을 고른다. 같은 가격 품목 둘('후라이드 20,000' '양념 20,000')과 헷갈리지 않게
    그 줄부터 아래에서 두 번 이상 나와야 하고, 그 위 품목 중 가장 비싼 것보다 작으면 안 되며, 산수가 맞아야만 쓴다.
    """
    rows = [
        i
        for i in range(start, len(lines))
        if split[i][1] and i not in tax_idx and not _has(lines[i].text, rules.tax_keywords)
    ]
    counts = Counter(split[i][1][-1] for i in rows)
    in_found = {i for i, _ in found}
    for amount in sorted((a for a, c in counts.items() if c >= 2 and a >= rules.min_amount), reverse=True):
        hits = [i for i in rows if split[i][1][-1] == amount]
        for k in hits[:-1]:  # 이 줄과 그 아래에 한 번 더 나와야 결제 줄
            items_above = [it.amount for i, it in found if i < k]
            if not items_above or amount < max(items_above):
                continue
            negs = {-split[i][1][-1] for i in range(start, k) if i not in in_found and split[i][1] and split[i][1][-1] < 0}
            above = sum(items_above)
            if above == amount or above - amount in negs:
                return amount, k, above - amount
    return None


def _cell_quantity(unit: int | None, qty: int | None, amount: int, rules: ParseRules) -> tuple[int | None, int | None]:
    """표에서 읽은 단가 · 수량 중 빈 칸을 금액으로 채운다. (수량, 단가)"""
    if qty is None and unit and amount % unit == 0 and 0 < amount // unit <= rules.max_quantity:
        qty = amount // unit
    if unit is None and qty and amount % qty == 0:
        unit = amount // qty
    return qty, unit


# 단가×수량이 어긋난 품목이 이보다 많으면 조합(2^n)을 다 보지 않는다
_MAX_FIX_CANDIDATES = 12


def _reconcile(items: list[ParsedItem], total: int | None) -> list[str]:
    """단가×수량 ≠ 금액인 품목은 금액과 단가×수량 중 하나를 잘못 읽은 것이다.

    품목 합이 합계와 정확히 맞는 조합 중 고친 칸이 가장 적은 것을 고른다. 합계도 잘못 읽었으면 틀린 쪽에 맞출 수 있어서
    고친 칸은 반드시 경고로 알린다. 맞는 조합이 없으면 고치지 않고 어긋난 품목만 알린다.
    """
    odd = [
        it
        for it in items
        if it.kind == ITEM and it.quantity and it.unit_price and it.quantity * it.unit_price != it.amount
    ]
    if not odd:
        return []
    if total is not None and len(odd) <= _MAX_FIX_CANDIDATES:
        diff = total - sum(it.amount for it in items)
        for k in range(len(odd) + 1):
            combo = next(
                (c for c in combinations(odd, k) if sum(it.quantity * it.unit_price - it.amount for it in c) == diff),
                None,
            )
            if combo is None:
                continue
            if not combo:
                return []  # 금액 칸끼리는 합계와 맞으니 단가나 수량을 잘못 읽은 것. 초안(금액)은 그대로 둔다
            notes = []
            for it in combo:
                fixed = it.quantity * it.unit_price
                notes.append(f"'{it.name}' {it.amount:,}원 → {fixed:,}원")
                it.amount = fixed
            return [f"단가×수량으로 금액을 고쳐 합계와 맞췄습니다: {', '.join(notes)}. 맞는지 확인해 주세요."]
    names = ", ".join(f"'{it.name}'" for it in odd[:3])
    return [f"단가×수량과 금액이 다른 품목이 있습니다: {names}. 금액을 확인해 주세요."]


def parse_receipt(lines: list[Line], rules: ParseRules | None = None) -> ParsedReceipt:
    """글자 줄 목록(위에서 아래 순서) → 가게 이름 · 합계 · 품목."""
    rules = rules or ParseRules()
    lines = [replace(ln, text=_normalize(ln.text)) for ln in lines if ln.text.strip()]
    lines = _read_columns(lines, rules)
    lines = _merge_two_line_items(lines, rules)
    split = [
        (ln.cells[0], [n for n in ln.cells[1:] if n is not None]) if ln.cells else _split(ln.text, rules)
        for ln in lines
    ]
    roles = ["other"] * len(lines)

    for i, ln in enumerate(lines):
        if _has(ln.text, rules.ignore_keywords) or any(re.search(p, _compact(ln.text)) for p in rules.ignore_patterns):
            roles[i] = "ignored"
        elif _is_header(ln.text, split[i][1], rules):
            roles[i] = "header"

    # 합계: 우선순위가 높은 낱말 묶음부터 찾고, 같은 묶음이 여러 줄이면 마지막 줄
    total, total_idx = None, None
    for group in rules.total_keywords:
        hits = [
            i
            for i, ln in enumerate(lines)
            if roles[i] == "other"
            and split[i][1]
            and split[i][1][-1] >= rules.min_amount
            and _has(ln.text, group)
            and not _has(ln.text, rules.total_exclude_keywords)
        ]
        if hits:
            total_idx = hits[-1]
            total = split[total_idx][1][-1]
            break
    for i, ln in enumerate(lines):
        # 금액이 없는 줄('상품수 소계:5')은 합계 낱말이 있어도 품목 구간을 끊지 않는다
        has_amount = bool(split[i][1]) and abs(split[i][1][-1]) >= rules.min_amount
        if roles[i] == "other" and has_amount and any(_has(ln.text, g) for g in rules.total_keywords):
            roles[i] = "total" if i == total_idx else "subtotal"

    # 세금 줄(면세 · 과세 · 부가세)은 낱말을 잘못 읽어도 품목이 아니다
    tax_idx, tax_total = _tax_lines(lines, split, roles, rules)
    for k in tax_idx:
        if roles[k] == "other":
            roles[k] = "ignored"
    if total is None:  # 합계 낱말을 못 읽었으면 세금 합(면세 + 과세 + 부가세)이 합계다
        total = tax_total

    # 품목: 머리줄 아래 ~ 첫 합계 줄 위. 할인은 합계 줄 사이에 오는 경우가 많아 결제금액 줄 위까지 본다
    header_idx = next((i for i, r in enumerate(roles) if r == "header"), None)
    first_total = next((i for i, r in enumerate(roles) if r in ("total", "subtotal")), len(lines))
    last = total_idx if total_idx is not None else len(lines)
    if tax_idx:  # 세금 줄 아래도 품목이 아니다 (합계 낱말을 못 읽은 영수증에서는 이것이 품목 구간의 끝)
        first_total = min(first_total, tax_idx[0])
        if total_idx is None:
            last = tax_idx[0]
    found: list[tuple[int, ParsedItem]] = []
    for i in range(header_idx + 1 if header_idx is not None else 0, last):
        name, nums = split[i]
        if roles[i] != "other" or not nums or not _LETTER.search(name):
            continue
        amount = nums[-1]
        # 할인 낱말 없이 금액 뒤에 빼기만 붙인 할인 ('단팥호빵 … 1,000-T'). 앞에 붙은 빼기만 있는 줄은 4회차 실험에서
        # 다른 영수증의 소계 찾기를 깨뜨려서(보고서 4-1) 할인으로 보지 않는다
        if _has(name, rules.discount_keywords) or (amount < 0 and _minus_after_amount(lines[i].text, rules)):
            found.append((i, ParsedItem(name, -abs(amount), DISCOUNT)))
            roles[i] = "discount"
        elif i < first_total and rules.min_amount <= amount <= rules.max_amount:
            cells = lines[i].cells
            qty, unit = _cell_quantity(cells[1], cells[2], amount, rules) if cells else _quantity(nums, rules)
            found.append((i, ParsedItem(name, amount, ITEM, qty, unit)))
            roles[i] = "item"

    # 합계 낱말을 못 읽은 줄 찾기: 숫자가 하나뿐이고 금액이 위 품목들의 합과 같으면 합계(소계) 줄로 본다.
    # 수량 · 단가가 찍힌 품목 줄은 숫자가 둘 이상이라 여기에 걸리지 않는다
    kept: list[tuple[int, ParsedItem]] = []
    running, inferred = 0, None
    for i, item in found:
        if item.kind == ITEM and len(kept) >= 2 and len(split[i][1]) == 1 and item.amount == running:
            inferred, roles[i] = i, "subtotal"
        elif inferred is not None and item.kind == ITEM:
            roles[i] = "other"  # 합계 줄 아래의 '품목'은 영수증 아래쪽 잡글로 본다
        else:
            kept.append((i, item))
            running += item.amount
    if total is None and inferred is not None:
        total, total_idx, roles[inferred] = split[inferred][1][-1], inferred, "total"

    # 반복 금액(6회차): 합계를 못 찾았거나, 찾은 합계가 할인 전 금액(반복 금액 + 그 위의 빼기 금액)이면
    # 반복 금액이 합계다. 그 줄부터 아래의 '품목'은 결제 줄이고, 산수에 쓴 빼기 줄은 할인이다
    start = header_idx + 1 if header_idx is not None else 0
    rep = _repeated_total(lines, split, kept, start, tax_idx, rules)
    if rep and (total is None or (rep[2] > 0 and total - rep[0] == rep[2])):
        amount, k, discount = rep
        if total_idx is not None:
            roles[total_idx] = "subtotal"
        for i, _ in kept:
            if i >= k:
                roles[i] = "other"
        if discount:  # _repeated_total이 산수에 쓴 빼기 줄 (품목 · 할인으로 잡히지 않은 줄)
            in_kept = {i for i, _ in kept}
            j = next(i for i in range(start, k) if i not in in_kept and split[i][1] and split[i][1][-1] == -discount)
            kept.append((j, ParsedItem(split[j][0] or "할인", -discount, DISCOUNT)))
            roles[j] = "discount"
        kept = sorted((f for f in kept if f[0] < k), key=lambda f: f[0])
        total, total_idx, roles[k] = amount, k, "total"
    items = [it for _, it in kept]
    fixes = _reconcile(items, total)

    # 가게 이름: '상호:' 줄이 있으면 그것, 없으면 품목 · 머리줄보다 위에서 글자로 된 첫 줄
    store = None
    for i, ln in enumerate(lines):
        if _has(ln.text, rules.store_keywords):
            store, roles[i] = _clean_store(ln.text, rules), "store"
            break
    if store is None:
        limit = min(
            (i for i, r in enumerate(roles) if r in ("item", "discount", "header", "total", "subtotal")),
            default=len(lines),
        )
        for i in range(limit):
            name, nums = split[i]
            if roles[i] == "other" and not nums and _LETTER.search(name) and len(_compact(name)) >= 2:
                store, roles[i] = _clean_store(name, rules), "store"
                break

    parsed = ParsedReceipt(
        store or None, total, items, [ParsedLine(ln.text, ln.conf, r) for ln, r in zip(lines, roles, strict=True)], []
    )
    parsed.warnings = fixes + _warnings(parsed, rules)
    return parsed


def _warnings(p: ParsedReceipt, rules: ParseRules) -> list[str]:
    """사람이 확인할 곳을 알려 준다. 영수증은 '확인 중' 상태로 만들어지니 고칠 기회가 있다."""
    out = []
    if p.store_name is None:
        out.append("가게 이름을 찾지 못했습니다.")
    if not p.items:
        out.append("품목을 하나도 찾지 못했습니다.")
    if p.total_amount is None:
        out.append("합계 금액을 찾지 못했습니다.")
    elif p.items and p.check()["difference"]:
        out.append(
            f"품목 합({p.items_sum:,}원)과 합계({p.total_amount:,}원)가 {p.check()['difference']:,}원 다릅니다. "
            "빠진 품목이나 잘못 읽은 숫자가 있을 수 있어요."
        )
    low = [ln for ln in p.lines if ln.role in ("item", "discount", "total") and ln.conf < rules.low_confidence]
    if low:
        out.append(f"흐리게 읽힌 줄이 {len(low)}개 있습니다: " + ", ".join(f"'{ln.text}'" for ln in low[:3]))
    return out
