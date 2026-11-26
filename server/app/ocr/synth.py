"""평가용 가짜 영수증 사진 만들기.

samples/*.json 가운데 "synth" 칸이 있는 것을 사진(.jpg)으로 그린다. 진짜 영수증 사진은
같은 이름의 .jpg/.png와 정답 .json(synth 칸 없이)을 넣으면 그대로 채점에 쓰인다.

    python -m app.ocr.synth        # samples 폴더의 가짜 영수증을 모두 다시 그린다

synth 칸: layout(table · simple · two_line), font(malgun · gulim · batang), size, store_style(plain · bracket · sangho),
subtotal_label · total_label, pay(card · cash), 사진 효과 rotate(도) · blur · noise(0~0.3) · shadow(0~0.6) · jpeg, seed
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SAMPLES = Path(__file__).parent / "samples"
FONTS = {
    "malgun": [r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"],
    "gulim": [r"C:\Windows\Fonts\gulim.ttc", "/usr/share/fonts/truetype/nanum/NanumGothicCoding.ttf"],
    "batang": [r"C:\Windows\Fonts\batang.ttc", "/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf"],
}
WIDTH, LEFT, UNIT, QTY = 640, 24, 380, 450
RIGHT = WIDTH - 24


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS[name]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"글꼴을 찾을 수 없습니다: {name} ({FONTS[name]})")


def _won(n: int) -> str:
    return f"{n:,}"


def _rows(answer: dict, s: dict, rnd: random.Random) -> list[list[tuple[str, int, str]]]:
    """영수증 줄 목록. 줄 = [(글자, x, 정렬)], 정렬 la=왼쪽 ra=오른쪽 ma=가운데, 'RULE' = 구분선."""
    store, rows = answer["store_name"], []
    style = s.get("store_style", "plain")
    if style == "sangho":
        rows += [[("영 수 증", WIDTH // 2, "ma")], [(f"상호: {store}", LEFT, "la")]]
    else:
        rows.append([(f"[{store}]" if style == "bracket" else store, WIDTH // 2, "ma")])
    rows += [
        [(f"사업자번호 {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10000, 99999)}", LEFT, "la")],
        [
            (f"대표 {rnd.choice(['김정산', '이나눔', '박같이', '최영수'])}", LEFT, "la"),
            (f"TEL 031-{rnd.randint(200, 999)}-{rnd.randint(1000, 9999)}", RIGHT, "ra"),
        ],
        [(f"주소 경기도 수원시 영통구 광교산로 {rnd.randint(1, 300)}", LEFT, "la")],
        [
            (f"2026-11-{rnd.randint(1, 8):02d} {rnd.randint(11, 22)}:{rnd.randint(0, 59):02d}", LEFT, "la"),
            (f"POS {rnd.randint(1, 9):02d}", RIGHT, "ra"),
        ],
        [("RULE", 0, "")],
    ]
    items = [i for i in answer["items"] if i["kind"] == "ITEM"]
    discounts = [i for i in answer["items"] if i["kind"] == "DISCOUNT"]
    layout = s.get("layout", "table")
    if layout == "table":
        rows += [
            [("상품명", LEFT, "la"), ("단가", UNIT, "ra"), ("수량", QTY, "ra"), ("금액", RIGHT, "ra")],
            [("RULE", 0, "")],
        ]
    for it in items:
        if layout == "table":
            rows.append(
                [
                    (it["name"], LEFT, "la"),
                    (_won(it["unit_price"]), UNIT, "ra"),
                    (str(it["quantity"]), QTY, "ra"),
                    (_won(it["amount"]), RIGHT, "ra"),
                ]
            )
        elif layout == "simple":
            rows.append([(it["name"], LEFT, "la"), (str(it["quantity"]), QTY, "ra"), (_won(it["amount"]), RIGHT, "ra")])
        else:  # two_line: 이름 줄 + '단가 x 수량  금액' 줄
            rows += [
                [(it["name"], LEFT, "la")],
                [(f"{_won(it['unit_price'])} x {it['quantity']}", LEFT + 40, "la"), (_won(it["amount"]), RIGHT, "ra")],
            ]
    rows.append([("RULE", 0, "")])
    total = answer["total_amount"]
    if discounts:
        rows.append(
            [(s.get("subtotal_label", "합계"), LEFT, "la"), (_won(sum(i["amount"] for i in items)), RIGHT, "ra")]
        )
        rows += [[(d["name"], LEFT, "la"), (_won(d["amount"]), RIGHT, "ra")] for d in discounts]
        rows.append([(s.get("total_label", "결제금액"), LEFT, "la"), (_won(total), RIGHT, "ra")])
    else:
        rows.append([(s.get("total_label", "합계"), LEFT, "la"), (_won(total), RIGHT, "ra")])
    vat = round(total / 11)
    rows += [
        [("RULE", 0, "")],
        [("공급가액", LEFT, "la"), (_won(total - vat), RIGHT, "ra")],
        [("부가세", LEFT, "la"), (_won(vat), RIGHT, "ra")],
        [("RULE", 0, "")],
    ]
    if s.get("pay") == "cash":
        paid = -(-total // 10000) * 10000
        rows += [
            [("받은금액", LEFT, "la"), (_won(paid), RIGHT, "ra")],
            [("거스름돈", LEFT, "la"), (_won(paid - total), RIGHT, "ra")],
        ]
    else:
        rows += [
            [("신용카드", LEFT, "la"), (f"1234-56**-****-{rnd.randint(1000, 9999)}", RIGHT, "ra")],
            [("승인번호", LEFT, "la"), (str(rnd.randint(10_000_000, 99_999_999)), RIGHT, "ra")],
            [("승인금액", LEFT, "la"), (_won(total), RIGHT, "ra")],
        ]
    rows.append([("감사합니다. 또 오세요!", WIDTH // 2, "ma")])
    return rows


def render(answer: dict) -> Image.Image:
    s = answer["synth"]
    rnd = random.Random(s.get("seed", 0))
    font = _font(s.get("font", "malgun"), s.get("size", 22))
    line_h = int(font.size * 1.6)
    rows = _rows(answer, s, rnd)
    paper = Image.new("L", (WIDTH, 60 + line_h * len(rows)), 248)
    draw = ImageDraw.Draw(paper)
    for n, row in enumerate(rows):
        y = 30 + n * line_h
        if row[0][0] == "RULE":
            for x in range(LEFT, RIGHT, 12):  # 점선
                draw.line([(x, y + line_h // 3), (x + 6, y + line_h // 3)], fill=90, width=2)
            continue
        for text, x, anchor in row:
            draw.text((x, y), text, font=font, fill=rnd.randint(15, 60), anchor=anchor)

    # 사진처럼: 책상 위에 놓고, 기울이고, 흐리게, 잡음, 그림자, JPEG 압축
    desk = rnd.randint(90, 140)
    img = Image.new("L", (paper.width + 160, paper.height + 160), desk)
    img.paste(paper, (80, 80))
    img = img.rotate(s.get("rotate", 0), resample=Image.Resampling.BICUBIC, fillcolor=desk)
    if s.get("blur"):
        img = img.filter(ImageFilter.GaussianBlur(s["blur"]))
    if s.get("noise"):
        img = Image.blend(img, Image.effect_noise(img.size, 60), s["noise"])
    if s.get("shadow"):
        shade = Image.linear_gradient("L").rotate(rnd.choice([0, 90, 180, 270])).resize(img.size)
        img = ImageChops.multiply(img, shade.point(lambda p: 255 - int(p * s["shadow"])))
    return img


def main() -> None:
    count = 0
    for path in sorted(SAMPLES.glob("*.json")):
        answer = json.loads(path.read_text(encoding="utf-8"))
        if "synth" in answer:
            render(answer).convert("RGB").save(
                path.with_suffix(".jpg"), "JPEG", quality=answer["synth"].get("jpeg", 85)
            )
            count += 1
    print(f"가짜 영수증 {count}장을 그렸습니다: {SAMPLES}")


if __name__ == "__main__":
    main()
