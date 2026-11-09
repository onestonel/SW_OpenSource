"""글자 줄 → 영수증 초안 (규칙 기반).

판단 기준(낱말 · 숫자 범위)은 전부 ParseRules 한 곳에 모았다. 새 모양의 영수증을 잘못 읽으면
여기 낱말을 더하고 `python -m app.ocr.bench`로 점수가 오르는지 확인한다.
나중에 LLM으로 바꾸고 싶으면 parse_receipt와 같은 모양(줄 목록 → ParsedReceipt)의 함수를 만들면 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
    # 합계 낱말. 앞 묶음일수록 우선한다 (할인 뒤 실제 낸 돈 > 할인 전 합계 > 소계)
    total_keywords: tuple[tuple[str, ...], ...] = (
        ("결제금액", "받을금액", "청구금액", "총결제", "결제합계"),
        ("합계", "총액", "총금액", "TOTAL"),
        ("소계",),
    )
    # 합계 낱말이 있어도 금액이 아닌 줄 (합계수량 12 → 12원이 아님)
    total_exclude_keywords: tuple[str, ...] = ("수량", "건수", "개수")
    discount_keywords: tuple[str, ...] = ("할인", "DC", "쿠폰", "에누리")
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
    """글자 한 줄과 OCR 확신도(0~1)."""

    text: str
    conf: float = 1.0


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
_SKIP_TOKENS = {"x", "X", "×", "*", "@", "=", "|"}
_NAME_STRIP = " :：·-=|[]【】<>'\"`"  # 괄호 ()는 '탕수육(소)'처럼 이름의 일부라 남긴다


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


def _split(text: str, rules: ParseRules) -> tuple[str, list[int]]:
    """줄을 '이름 부분'과 '끝에 붙은 숫자들'로 나눈다. '김치찌개 9,000 2 18,000' → ('김치찌개', [9000, 2, 18000])"""
    tokens = _normalize(text).split()
    nums: list[int] = []
    while tokens:
        tok = tokens[-1]
        if tok in _SKIP_TOKENS:
            tokens.pop()
            continue
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
    name = re.sub(r"^\d{1,3}[.)]?\s+", "", " ".join(tokens))  # 앞의 순번 '01 김치찌개' 떼기
    return name.strip(_NAME_STRIP), nums


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


def _merge_two_line_items(lines: list[Line], rules: ParseRules) -> list[Line]:
    """'이름만 있는 줄' 다음에 '숫자만 있는 줄'이 오면 한 줄로 합친다 (메뉴 이름을 따로 찍는 영수증)."""
    out: list[Line] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i + 1 < len(lines):
            name, nums = _split(cur.text, rules)
            next_name, next_nums = _split(lines[i + 1].text, rules)
            if (
                name
                and not nums
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


def parse_receipt(lines: list[Line], rules: ParseRules | None = None) -> ParsedReceipt:
    """글자 줄 목록(위에서 아래 순서) → 가게 이름 · 합계 · 품목."""
    rules = rules or ParseRules()
    lines = [Line(_normalize(ln.text), ln.conf) for ln in lines if ln.text.strip()]
    lines = _merge_two_line_items(lines, rules)
    split = [_split(ln.text, rules) for ln in lines]
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
        if roles[i] == "other" and any(_has(ln.text, g) for g in rules.total_keywords):
            roles[i] = "total" if i == total_idx else "subtotal"

    # 품목: 머리줄 아래 ~ 첫 합계 줄 위. 할인은 합계 줄 사이에 오는 경우가 많아 결제금액 줄 위까지 본다
    header_idx = next((i for i, r in enumerate(roles) if r == "header"), None)
    first_total = next((i for i, r in enumerate(roles) if r in ("total", "subtotal")), len(lines))
    last = total_idx if total_idx is not None else len(lines)
    found: list[tuple[int, ParsedItem]] = []
    for i in range(header_idx + 1 if header_idx is not None else 0, last):
        name, nums = split[i]
        if roles[i] != "other" or not nums or not _LETTER.search(name):
            continue
        amount = nums[-1]
        if _has(name, rules.discount_keywords):
            found.append((i, ParsedItem(name, -abs(amount), DISCOUNT)))
            roles[i] = "discount"
        elif i < first_total and rules.min_amount <= amount <= rules.max_amount:
            qty, unit = _quantity(nums, rules)
            found.append((i, ParsedItem(name, amount, ITEM, qty, unit)))
            roles[i] = "item"

    # 합계 낱말을 못 읽은 줄 찾기: 숫자가 하나뿐이고 금액이 위 품목들의 합과 같으면 합계(소계) 줄로 본다.
    # 수량 · 단가가 찍힌 품목 줄은 숫자가 둘 이상이라 여기에 걸리지 않는다
    items: list[ParsedItem] = []
    running, inferred = 0, None
    for i, item in found:
        if item.kind == ITEM and len(items) >= 2 and len(split[i][1]) == 1 and item.amount == running:
            inferred, roles[i] = i, "subtotal"
        elif inferred is not None and item.kind == ITEM:
            roles[i] = "other"  # 합계 줄 아래의 '품목'은 영수증 아래쪽 잡글로 본다
        else:
            items.append(item)
            running += item.amount
    if total is None and inferred is not None:
        total, total_idx, roles[inferred] = split[inferred][1][-1], inferred, "total"

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
    parsed.warnings = _warnings(parsed, rules)
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
